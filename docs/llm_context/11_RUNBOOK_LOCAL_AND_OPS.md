---
title: 로컬/운영 런북
last_synced: 2026-02-04
sync_source:
  - dashboard/server/main.py
  - start.sh
  - org_tables_v2.html
  - salesmap_first_page_snapshot.py
---

## Purpose
- 로컬 개발·운영 시 필요한 기동 커맨드, 환경 변수, 캐시/DB 교체 동작을 SSOT로 제공한다.

## Behavioral Contract
### 로컬 실행
- 백엔드: `python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload`
  - DB_PATH 기본 `salesmap_latest.db`; 파일 없으면 `/api/*` 500.
- 프런트: `python -m http.server 8001` 후 `http://localhost:8001/org_tables_v2.html` (또는 파일을 직접 열기). API_BASE는 origin+/api, origin 없을 때 `http://localhost:8000/api`.
- 의존성: `python -m venv .venv && .venv/ Scripts/ pip install -r requirements.txt` (Windows 경로는 `\.venv\Scripts\pip`).

### 스냅샷 생성/교체
- 명령: `SALESMAP_TOKEN=... python salesmap_first_page_snapshot.py --db-path salesmap_latest.db --log-dir logs --checkpoint-dir logs/checkpoints --backup-dir backups --keep-backups 30`
- 옵션: `--resume`/`--resume-run-tag`, `--checkpoint-interval 50`, `--webform-only`, `--no-backup`, `--base-url`, `--token`, `--backup-dir`, `--keep-backups`.
- 산출물: `salesmap_latest.db`(또는 폴백 `<stem>_<run_tag>.db`), `logs/*.log`, `logs/run_history.jsonl`, `logs/checkpoints/*.json`, `backups/salesmap_backup_<run_tag>.zip`.

### 컨테이너/배포(start.sh)
- 필수 env: `DB_URL`(다운로드 소스), 선택: `DB_ALWAYS_REFRESH`(기본 1), `PORT`(기본 8000).
- 동작: DB 미존재 또는 refresh=1이면 Python 다운로더로 `${DB_URL}` → tmp 다운로드(50MB 미만이면 오류) → `/app/data/salesmap_latest.db` 저장 → `/app/salesmap_latest.db` 심링크 → `DB_PATH` 설정 → `python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port ${PORT:-8000}`.

### 프런트 캐시
- org_tables_v2는 화면별 Map 캐시만 존재, 무효화 없음. DB 교체 후 반드시 브라우저 새로고침.

## Invariants (Must Not Break)
- DB 기본 경로/심링크: 로컬·컨테이너 모두 `salesmap_latest.db` 사용, start.sh는 `/app/salesmap_latest.db` 심링크를 항상 갱신해야 한다.
- DB 다운로드 검증: 50MB 미만이면 실패로 종료한다.
- API_BASE 계산은 origin+/api fallback `http://localhost:8000/api` 고정.
- 스냅샷 토큰 필수, 교체 실패 시 폴백 DB 경로를 로그/run_history에 남겨야 한다.

## Coupling Map
- 서버: `dashboard/server/main.py`(DB_PATH 로드), `org_tables_api.py`, `database.py`.
- 스냅샷: `salesmap_first_page_snapshot.py`(DB 생성/교체, webform 후처리, run_history).
- 컨테이너: `start.sh`(DB 다운로드/검증/심링크/uvicorn 실행).
- 프런트: `org_tables_v2.html`(API_BASE 계산, 캐시).
- 관련 문서: `05_SNAPSHOT_PIPELINE_CONTRACT.md`, `06_API_CONTRACT_CORE.md`, `09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`.

## Edge Cases & Failure Modes
- DB 잠금/부재 → `/api/*` 500. start.sh 다운로드 실패/파일 잠금 시 종료.
- 파일 열기(origin null) 시 API_BASE가 `http://localhost:8000/api`로 강제된다.
- 스냅샷 교체가 WinError 32/5로 실패하면 폴백 DB가 생성될 수 있고 FastAPI는 기존 DB를 계속 읽는다.
- 캐시(성능/DRI/PL 등)가 DB mtime 기반 메모리에 남아 DB 교체 후 재시작/새로고침 전까지 이전 데이터를 반환.

## Verification
- 로컬: uvicorn 기동 후 `curl http://localhost:8000/api/health` → `{status:"ok"}` 확인, `/api/orgs` 호출 성공.
- 컨테이너: `DB_URL` 설정 후 `bash start.sh`; 다운로드 크기 50MB 이상, `/app/salesmap_latest.db` 심링크 존재 확인.
- 스냅샷: 실행 후 `logs/run_history.jsonl`에 final_db_path/log_path/backup_path 기록, DB가 해당 경로인지 확인.
- 프런트: 새 DB 배포 후 브라우저 새로고침 시 최신 데이터 표시, 새로고침 없이 남은 캐시가 있는지 확인.

## Refactor-Planning Notes (Facts Only)
- DB 경로/API_BASE/포트 상수가 코드 여러 곳에 중복돼 있어 환경 변경 시 동시 수정 필요.
- 프런트 캐시 무효화가 없어 배포 시 사용자가 새로고침하지 않으면 이전 데이터를 볼 수 있다.
- 스냅샷 실패/체크포인트 실패 시 알림/모니터링이 없으며 수동 확인이 필요하다.
