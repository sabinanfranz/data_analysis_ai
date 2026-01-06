---
title: User Guide (PowerShell/로컬 실행)
last_synced: 2026-01-06
sync_source:
  - dashboard/server/main.py
  - org_tables_v2.html
  - start.sh
  - salesmap_first_page_snapshot.py
  - docs/org_tables_v2.md
---

## Purpose
- 로컬에서 FastAPI 백엔드와 정적 프런트 `org_tables_v2.html`을 실행하고, Salesmap 스냅샷 스크립트를 돌리는 최소 절차를 코드 기준으로 안내한다.

## Behavioral Contract
- **백엔드 기동**: `python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload`로 실행한다. `main.py`는 `dashboard/server/database.py`를 로드하며 `DB_PATH`(기본 `salesmap_latest.db`)가 없으면 `/api/*`가 500을 반환한다. `start.sh` 컨테이너 엔트리는 `DB_URL`로 DB를 다운로드한 뒤 `uvicorn ...:app`을 실행한다.
- **프런트 열기**: 정적 서버로 `python -m http.server 8001` 실행 후 `http://localhost:8001/org_tables_v2.html`을 연다(또는 파일을 직접 열어도 동작). `org_tables_v2.html`은 origin이 있으면 `<origin>/api`, 없으면 `http://localhost:8000/api`를 `API_BASE`로 사용하므로 백엔드와 동일 호스트/포트가 필요하다.
- **가상환경/의존성**: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`(PowerShell)로 설치한다. JS 기반 프런트 테스트를 돌릴 경우 `node_modules`가 필요하지만 프런트 HTML 실행 자체에는 추가 빌드가 없다.
- **Salesmap 스냅샷 실행**: `salesmap_first_page_snapshot.py`는 `SALESMAP_TOKEN`을 필수로 요구하며, 기본 DB 경로는 `salesmap_latest.db`, 로그는 `logs/`, 체크포인트는 `logs/checkpoints`를 사용한다. 예시:
  - 전체 스냅샷: `$env:SALESMAP_TOKEN="<토큰>"; python .\salesmap_first_page_snapshot.py --db-path .\salesmap_latest.db --log-dir .\logs --checkpoint-dir .\logs\checkpoints --backup-dir .\backups --keep-backups 30`
  - 재개 실행: 위 옵션 + `--resume` 또는 특정 `--resume-run-tag`.
  - 웹폼만 후처리: `$env:SALESMAP_TOKEN="<토큰>"; python .\salesmap_first_page_snapshot.py --webform-only --db-path .\salesmap_latest.db --log-dir .\logs`
- **조직/People 탐색 흐름**: 프런트는 `getSizes`→`/orgs`→조직 선택→`/orgs/{id}/people`→사람/딜/메모→`/orgs/{id}/won-groups-json` 순으로 호출한다. DB가 바뀌면 브라우저 새로고침을 해야 캐시가 초기화된다.

## Invariants (Must Not Break)
- 백엔드/프런트 기본 포트 조합(`8000` API, `8001` 정적 서버)과 `API_BASE` 계산 방식(origin+/api 또는 `http://localhost:8000/api`)을 유지해야 한다.
- `DB_PATH` 기본값은 `salesmap_latest.db`이고 start.sh도 동일 경로를 `/app/salesmap_latest.db`로 심볼릭 링크한다.
- 스냅샷 실행은 `SALESMAP_TOKEN` 없으면 즉시 종료하며, 체크포인트/로그/백업 경로 기본값은 코드 상수(DEFAULT_*). `--webform-only`는 기존 DB를 덮어쓰지 않고 webform_history만 갱신한다.
- 프런트는 fetch 캐시를 Map에 보존하므로 DB 교체나 포트 변경 시 새로고침 없이는 이전 결과를 계속 사용한다.

## Coupling Map
- 실행 스크립트: `start.sh`(컨테이너), `dashboard/server/main.py`(FastAPI), `org_tables_v2.html`(정적 프런트).
- 데이터 스냅샷: `salesmap_first_page_snapshot.py`가 SQLite를 생성/교체하고 백엔드가 이를 직접 읽는다.
- 문서/UX: 상세 화면/정렬 규칙은 `docs/org_tables_v2.md`와 API 계약(`docs/api_behavior.md`)에 정리되어 있다.

## Edge Cases & Failure Modes
- DB 파일이 없거나 잠겨 있으면 백엔드 `/api/*`가 500을 반환한다. start.sh는 DB 다운로드가 50MB 미만이면 오류로 중단한다.
- 스냅샷 실행 중 파일 잠금 발생 시 `replace_file_with_retry`가 최대 5회 재시도 후 폴백 경로에 tmp를 저장하고 로그에 남긴다.
- PowerShell에서 venv 활성화가 실패하면 `.\.venv\Scripts\python.exe` 경로를 직접 지정해야 한다. Windows에서 체크포인트 rename 권한 문제가 있으면 `.tmp`를 `.json`으로 수동 복사 후 `--resume`을 사용한다.
- 프런트를 파일로 직접 열 때(`file://`)는 origin이 null이라 `API_BASE`가 `http://localhost:8000/api`로 강제된다.

## Verification
- `uvicorn dashboard.server.main:app --reload` 실행 후 `/api/health`가 `{"status":"ok"}`인지, `/api/orgs` 호출이 성공하는지 확인한다.
- `python -m http.server 8001`로 `org_tables_v2.html`을 열고 사이드바/메뉴 클릭 시 `/api/*` 호출이 정상적으로 이루어지는지 DevTools Network에서 확인한다.
- 스냅샷 실행 후 `logs/run_history.jsonl`과 최종 DB 경로가 기록되며 `salesmap_latest.db`가 최신 타임스탬프로 교체됐는지 확인한다.
- `--webform-only` 실행 시 기존 DB의 webform_history 테이블 row 수가 증가하고 다른 테이블은 변경되지 않는지 spot-check한다.

## Refactor-Planning Notes (Facts Only)
- API_BASE 결정 로직이 프런트 단일 상수로 하드코딩돼 있어 포트/경로가 바뀌면 HTML 수정이 필요하다.
- 스냅샷/백엔드/프런트 모두 DB 경로를 상수(`salesmap_latest.db`)로 가정하고 있으므로 경로를 바꾸려면 start.sh, main.py, 프런트 상수를 동시에 변경해야 한다.
- 스냅샷 로그/체크포인트/백업 경로도 코드 상수로 중복 정의돼 있어 실행 환경별 경로를 분리하기 어렵다.
