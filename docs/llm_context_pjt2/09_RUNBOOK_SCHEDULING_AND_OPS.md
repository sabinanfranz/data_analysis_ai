---
title: 운영 런북 (PJT2) – 스케줄링/로그/폴백
last_synced: 2026-02-05
sync_source:
  - dashboard/server/report_scheduler.py
  - dashboard/server/org_tables_api.py
  - dashboard/server/deal_normalizer.py
  - dashboard/server/main.py
---

# 운영 런북 (PJT2) – 스케줄링/로그/폴백

## Purpose
- 카운터파티 리스크 리포트 일일 생성/캐시/폴백/재시도를 운영자가 재현·장애 대응할 수 있도록 절차를 문서화한다.

## Behavioral Contract
- FastAPI startup 이벤트에서 start_scheduler()가 호출되며, ENABLE_SCHEDULER=0이면 즉시 반환되어 스케줄러는 뜨지 않는다.
- REPORT_CRON(기본 0 8 * * *, TZ=Asia/Seoul)으로 APScheduler가 모드 리스트(REPORT_MODES, 기본 offline,online)를 순차 실행한다. DB가 안정창(180s)보다 최신이면 리트라이 후 실패 시 기존 캐시를 유지한다.
- 캐시는 원자적으로 저장(off: `report_cache/{as_of}.json`, on: `report_cache/counterparty-risk/online/{as_of}.json`), status는 mode별(status.json/status_online.json)에 last_run/last_success 기록. LLM 실패는 폴백으로 채워도 SUCCESS로 간주된다.
- API는 캐시 우선 제공, cache miss 시 run_daily_counterparty_risk_job(force=True)로 생성 후 제공, 실패 시 last_success를 meta.is_stale=true로 반환한다.

## Invariants
- cron: REPORT_CRON 기본 \"0 8 * * *\" (TZ=Asia/Seoul); REPORT_MODES로 실행 모드 배열 제어, ENABLE_PROGRESS_SCHEDULER=1일 때 PROGRESS_CRON 별도 실행.
- 락: `report_cache/.counterparty_risk.lock` (POSIX fcntl / Windows msvcrt) 공용, 획득 실패 시 SKIPPED_LOCKED.
- 스냅샷: `report_work/salesmap_snapshot_<as_of>_<HHMMSS>.db` 로컬 복사 후 읽기 전용 사용, DB_STABLE_WINDOW_SEC(기본 180s)보다 오래된 경우만 진행.
- 캐시: offline `report_cache/{as_of}.json`, online `report_cache/counterparty-risk/online/{as_of}.json`; status 파일(status.json/status_online.json)은 retention 예외.
- fallback: 캐시 생성 실패 시 last_success 캐시를 meta.is_stale=true로 서빙.
- 환경 기본값: CACHE_DIR=report_cache, WORK_DIR=report_work, DB_RETRY=10, DB_RETRY_INTERVAL_SEC=30, CACHE_RETENTION_DAYS=14.
- DB 시그니처: `mtime-size` 문자열을 meta.status에 기록.
- 캐시 파일: tmp write + fsync + rename(atomic).
- retention: CACHE_RETENTION_DAYS 초과 json/jsonl/스냅샷을 정리하되 status 파일은 건드리지 않는다(run_logs/*.jsonl 포함).

## Coupling Map
- 스케줄/캐시/락: `dashboard/server/report_scheduler.py` (run_daily_counterparty_risk_job/all_modes, get_cached_report, start_scheduler).
- API 재생성/상태: `dashboard/server/org_tables_api.py` (`/report/counterparty-risk`, `/recompute`, `/status`).
- 리포트 생성 파이프라인: `dashboard/server/deal_normalizer.py`(build_counterparty_risk_report).

## Edge Cases
- DB mtime이 안정창보다 최신이면 DB_UNSTABLE_OR_UPDATING으로 리트라이 후 FAILED 기록, 캐시는 기존본 유지.
- 락 획득 실패 시 SKIPPED_LOCKED를 status에 기록하고 생성은 스킵한다.
- 캐시 없음 + 생성 실패 시 API는 last_success 캐시를 meta.is_stale=true로 반환, last_success가 없으면 500.
- LLM 오류/미설정은 리포트 실패로 취급되지 않으며 폴백 값으로 SUCCESS 처리된다.
- Windows에서도 msvcrt.locking으로 동일 락을 사용한다.

## Verification
- `python -m unittest discover -s tests`로 스케줄 관련 회귀 포함 전체 테스트 실행.
- `curl /api/report/counterparty-risk/status`로 status.json 구조/last_run 갱신 확인.
- Windows 환경에서 scheduler 실행 시 lock 획득/해제가 동작하는지 로그로 확인(msvcrt).
- 강제 재생성:  
  `curl -X POST "http://localhost:8000/api/report/counterparty-risk/recompute?date=2026-01-10&mode=offline"`  
  `curl -X POST "http://localhost:8000/api/report/counterparty-risk/recompute?date=2026-01-10&mode=online"`  
  → mode별 status last_run/result 확인.
- 캐시 제공:  
  `curl "http://localhost:8000/api/report/counterparty-risk?mode=offline"` / `?mode=online` → meta.as_of 오늘, 캐시 없으면 생성 후 반환.
- 스냅샷 확인: `ls report_work/salesmap_snapshot_*` 생성 여부.
- 락 동작: 두 번 동시에 run_daily 호출 시 하나는 SKIPPED_LOCKED 기록되는지 status 확인.
- 스케줄러 기동: main.py startup 이벤트에서 start_scheduler() 호출 여부 확인, ENABLE_SCHEDULER=0이면 스킵.

## Refactor-Planning Notes (Facts Only)
- start_scheduler가 main.py startup에 직접 연결되어 있어 uvicorn --reload나 멀티프로세스 시 중복 실행 가드(락) 외 추가 제어가 필요할 수 있다.
- file_lock은 로컬 파일 시스템을 전제로 하므로 NAS/클라우드 스토리지로 옮길 경우 msvcrt/fcntl 동작 보장이 떨어질 수 있다.
- status.json은 retention 대상에서 제외되어 운영 상태 확인의 단일 소스가 되므로 필드 변경 시 API `/status`와 프런트 문서도 동시에 수정해야 한다.
