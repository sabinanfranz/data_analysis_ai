---
title: 로컬/운영 런북
last_synced: 2026-12-11
sync_source:
  - dashboard/server/main.py
  - start.sh
  - org_tables_v2.html
  - docs/user_guide.md
  - salesmap_first_page_snapshot.py
---

## Purpose
- 로컬 개발 및 운영 시 필요한 기동/환경 변수/캐시 동작을 코드 기준으로 정리한다.

## Behavioral Contract
- 로컬 실행:
  - 백엔드: `python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload`. `main.py`는 `DB_PATH`(기본 `salesmap_latest.db`)가 없으면 500을 반환한다.
  - 프런트: `python -m http.server 8001` 후 `http://localhost:8001/org_tables_v2.html` 열기(또는 파일 직접 열기). API_BASE는 origin+/api 또는 `http://localhost:8000/api`.
  - 가상환경: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`.
- 컨테이너/운영(start.sh):
  - 환경 변수: `DB_URL`(필수, 50MB 미만은 실패), `DB_ALWAYS_REFRESH`(기본 1), `PORT`(기본 8000).
  - 동작: DB 미존재 또는 항상 새로고침 시 Python 다운로더로 DB를 tmp→`/app/data/salesmap_latest.db` 저장 후 `/app/salesmap_latest.db`에 심볼릭 링크, `DB_PATH`를 세팅하고 `uvicorn dashboard.server.main:app` 실행.
- 스냅샷:
  - `salesmap_first_page_snapshot.py`로 DB 생성/교체, run_history.jsonl 기록, webform_history 후처리. `SALESMAP_TOKEN` 필수.
- 프런트 캐시: org_tables_v2는 fetch 결과를 Map에 저장하며 무효화가 없으므로 DB 교체 후 새로고침 필요.

## Invariants (Must Not Break)
- DB 경로는 백엔드/프런트/컨테이너 모두 `salesmap_latest.db`를 기본으로 사용해야 한다.
- start.sh는 DB 다운로드 크기가 50MB 미만이면 오류로 중단한다.
- API_BASE 계산은 origin+/api 또는 `http://localhost:8000/api`로 고정이며, 포트/경로가 변경되면 HTML 수정을 동반한다.
- 스냅샷 실행은 토큰 미설정 시 종료하며, 교체 실패 시 폴백 DB 경로를 로그/run_history에 남긴다.

## Coupling Map
- 서버: `dashboard/server/main.py`, `dashboard/server/org_tables_api.py`, `dashboard/server/database.py`.
- 컨테이너: `start.sh`(DB 다운로드/링크/uvicorn).
- 프런트: `org_tables_v2.html`(API_BASE/캐시).
- 파이프라인: `salesmap_first_page_snapshot.py`(DB 생성/교체).
- 문서: `docs/user_guide.md`, `docs/snapshot_pipeline.md`, `docs/error_log.md`.

## Edge Cases & Failure Modes
- DB 잠금/부재 시 `/api/*`가 500을 반환한다. start.sh는 DB가 없으면 다운로드 후에도 실패 시 종료한다.
- 프런트를 파일로 직접 열면 origin이 null이라 API_BASE가 `http://localhost:8000/api`로 강제된다.
- Windows에서 체크포인트/DB 교체 rename이 실패하면 폴백 파일이 남아 FastAPI가 이전 DB를 계속 읽을 수 있다.

## Verification
- 로컬에서 uvicorn 기동 후 `/api/health`가 ok, `/api/orgs` 호출이 성공하는지 확인한다.
- start.sh 실행 시 DB 다운로드가 50MB 이상이고 `/app/salesmap_latest.db` 심볼릭 링크가 생성되는지 확인한다.
- 스냅샷 실행 후 run_history.jsonl에 final_db_path가 기록되고 FastAPI가 해당 DB를 읽는지 확인한다.
- 프런트에서 메뉴 전환 시 `/api/*` 호출이 정상이고, 새 DB 교체 후 새로고침을 해야 최신 데이터가 표시되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
 - DB 경로/API_BASE/포트가 코드 곳곳에 상수로 박혀 있어 운영 환경을 바꾸려면 start.sh, main.py, 프런트 HTML을 동시에 수정해야 한다.
 - 프런트 캐시 무효화가 없으므로 배포 시 사용자가 새로고침하지 않으면 이전 데이터를 볼 수 있다.
 - 스냅샷 교체 실패/체크포인트 실패 시 수동 조치가 필요하지만 자동 알림/모니터링은 없다.
