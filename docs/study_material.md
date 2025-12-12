# Study Material for `data_analysis_ai`

이 문서는 초보 개발자가 이 프로젝트를 빠르게 이해하고, 필요한 개념을 무엇부터 공부하면 좋을지 안내하는 가이드입니다.

## 1) 프로젝트 개요
- **목표**: Salesmap API 데이터를 SQLite로 스냅샷하고, FastAPI 백엔드로 조회 API를 제공하며, 정적/동적 프론트(`org_tables_v2.html`)로 조직/People/Deal/랭킹을 탐색합니다.
- **데이터 흐름**: Salesmap API → 스냅샷 스크립트(`salesmap_first_page_snapshot.py`) → SQLite(DB) → FastAPI(`/dashboard/server`) → 프론트(`org_tables_v2.html` fetch/render).

## 2) 폴더/파일 구조(핵심)
- `salesmap_first_page_snapshot.py`: 스냅샷 실행, 백오프/체크포인트/백업/웹폼 수집.
- `dashboard/server/`: FastAPI 백엔드, DB 조회/집계 로직(`database.py`), 라우터(`org_tables_api.py`), 앱 엔트리(`main.py`).
- `org_tables_v2.html`: 프런트 단일 HTML+JS. 상태/캐시를 가지고 API 호출 후 표/JSON/모달 렌더.
- `docs/`: 실행/구조/에러/일지 문서. (`user_guide.md`, `org_tables_v2.md`, `snapshot_pipeline.md`, `api_behavior.md`, `daily_progress.md`, `study_material.md`).
- `tests/`: Python 단위 테스트/JS 테스트.

## 3) 먼저 익힐 개념
- **Python 기본**: `requests`로 HTTP 호출, `sqlite3`/`pandas`로 DB 다루기, 로깅/예외 처리, 백오프(재시도).
- **FastAPI**: 간단한 GET 라우터 정의, uvicorn 실행법, pydantic 없이 dict 반환.
- **SQLite/SQL**: SELECT/JOIN 기본, PRAGMA, 동적 스키마 확장(TableWriter가 컬럼 추가).
- **프런트 JS**: `fetch`로 API 호출, 상태/캐시(Map), DOM 업데이트(표/버튼/토스트/모달).
- **데이터 정제**: 정규식, JSON 직렬화, 키 필터링(utm/전화/동의 등 제거).
- **테스트**: pytest 기본, node --test(프런트 무브라우저 테스트) 개념.

## 4) 실행 예시
- 백엔드: `uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000`
- 프런트(정적): `python -m http.server 8001` 후 `http://localhost:8001/org_tables_v2.html`
- 스냅샷: `SALESMAP_TOKEN=... python salesmap_first_page_snapshot.py --db-path salesmap_latest.db`
- 웹폼만: `python salesmap_first_page_snapshot.py --webform-only --db-path salesmap_latest.db`

## 5) 코드 읽기 가이드
1. `docs/*.md` 요약(특히 `org_tables_v2.md`, `snapshot_pipeline.md`, `api_behavior.md`).
2. `dashboard/server/database.py`: 주요 함수 흐름
   - webform 처리: `get_won_groups_json` → webform 날짜 집계, memo 전처리(utm 포함 폼만 정제, 전화/동의/utm 제거, 정보 부족/특수 문구 시 memo 제거).
   - Won 집계/랭킹/People/Deal/Memo 쿼리.
3. `org_tables_v2.html`: 상태/캐시 → fetch → render 흐름. 상위 조직 JSON 카드의 버튼 활성화 조건 등.
4. `salesmap_first_page_snapshot.py`: 백오프/체크포인트/백업 → temp DB → 교체 → webform_history 후처리.
5. 테스트: `tests/test_salesmap_first_page_snapshot.py`, `tests/test_won_groups_json.py`(webform/memo 필터), 프런트 JS 테스트.

## 6) 더 공부하면 좋은 키워드
- HTTP 백오프/재시도, Rate limit 대응.
- SQLite 잠금 이슈 대처, 파일 교체/백업 전략.
- UI 상태/캐시 전략, 에러 토스트 UX.
- 데이터 정규화/클린업(정규식, JSON 스키마).
- pytest/단위 테스트 작성법.

## 7) 작은 실습 과제 예시
- API 하나 추가/변경: 예) 특정 People 필터 추가 후 프런트 fetch/render 연동.
- 프런트 UX 개선: 에러 토스트/로딩 상태 추가, JSON 보기 모달에 검색/필터 넣기.
- 스냅샷 옵션 추가: 제한/샘플 모드 등 파라미터를 CLI에 추가하고 테스트.

## 8) 참고 링크 (스스로 검색)
- FastAPI 공식 문서, SQLite 튜토리얼, MDN fetch/DOM, pytest 기본 가이드.
