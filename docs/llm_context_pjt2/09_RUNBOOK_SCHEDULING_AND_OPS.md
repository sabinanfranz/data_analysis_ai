---
title: 운영 런북 (PJT2) – 스케줄링/로그/폴백
last_synced: 2026-01-10
sync_source:
  - dashboard/server/report_scheduler.py
  - dashboard/server/org_tables_api.py
  - dashboard/server/deal_normalizer.py
---

# 운영 런북 (PJT2) – 스케줄링/로그/폴백

## Purpose
- 카운터파티 리스크 리포트 일일 생성/캐시/폴백/재시도를 운영자가 재현·장애 대응할 수 있도록 절차를 문서화한다.

## Behavioral Contract
- 매일 08:00(Asia/Seoul) cron(APScheduler)으로 리포트를 생성하며, DB가 안정 상태가 아니면 재시도 후 실패 시 최근 성공본을 유지한다.
- 캐시는 `report_cache/YYYYMMDD.json`에 원자적 저장, status.json에 last_run/last_success 기록. LLM 실패는 폴백으로 채우고 성공으로 간주할 수 있다.
- API는 캐시 우선 제공, 캐시 없으면 생성(force) 후 제공, 실패 시 최근 성공본(meta.is_stale=true)을 반환한다.

## Invariants
- 환경 기본값: TZ=Asia/Seoul, REPORT_CRON="0 8 * * *", CACHE_DIR="report_cache", WORK_DIR="report_work", DB_STABLE_WINDOW_SEC=180, DB_RETRY=10, DB_RETRY_INTERVAL_SEC=30, CACHE_RETENTION_DAYS=14.
- DB 시그니처: `mtime-size` 문자열. DB 안정성: 최근 수정 ≥ 180초.
- 스냅샷: `report_work/salesmap_snapshot_<as_of>_<HHMMSS>.db`로 copy 후 집계.
- 락: `report_cache/.counterparty_risk.lock` 파일 락. 획득 실패 시 SKIPPED_LOCKED.
- 캐시 파일: tmp write + fsync + rename(atomic) → `report_cache/YYYYMMDD.json`.
- status.json: last_run(result/code/msg/as_of/db_signature), last_success(as_of/db_signature/generated_at).
- retention: 캐시/jsonl/스냅샷 14일 이상 삭제.
- ENABLE_SCHEDULER=0이면 스케줄러는 기동하지 않고 서버만 뜬다(수동 recompute만 허용).

## Coupling Map
- 스케줄/캐시/락: `dashboard/server/report_scheduler.py` (run_daily_counterparty_risk_job, get_cached_report, start_scheduler).
- API 재생성/상태: `dashboard/server/org_tables_api.py` (`/report/counterparty-risk`, `/recompute`, `/status`).
- 리포트 생성 파이프라인: `dashboard/server/deal_normalizer.py`(build_counterparty_risk_report).

## Edge Cases
- DB 교체 직후(3분 미만) 스케줄 실행 → DB_UNSTABLE_OR_UPDATING 재시도 후 실패 가능. 실패해도 기존 캐시 유지, status=FAILED.
- 캐시 쓰기 실패 → 기존 캐시 보존. status에 CACHE_WRITE_FAILED 기록 필요(추가 개선).
- LLM 실패 → 폴백 evidence/actions로 채워 SUCCESS_WITH_FALLBACK 취급(전체 실패 아님).
- 캐시 없음 + 생성 실패 → API에서 last_success 캐시로 폴백, meta.is_stale=true.

## Verification
- 강제 재생성:  
  `curl -X POST "http://localhost:8000/api/report/counterparty-risk/recompute?date=2026-01-10"` → status.json last_run/result 확인.
- 캐시 제공:  
  `curl "http://localhost:8000/api/report/counterparty-risk"` → meta.as_of 오늘, 캐시 없으면 생성 후 반환.
- 스냅샷 확인: `ls report_work/salesmap_snapshot_*` 생성 여부.
- 락 동작: 두 번 동시에 run_daily 호출 시 하나는 SKIPPED_LOCKED 기록되는지 status 확인.
- 스케줄러 기동: start_scheduler()가 호출되는지 배포 시 main 엔트리에서 확인(현재 수동 연결 필요).***
