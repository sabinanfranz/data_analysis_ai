# org_tables (정적) 계약 – build_org_tables.py 버전

> 이 문서는 정적 HTML(`org_tables.html`) 버전에 대한 UI/상태 계약을 분리해 설명합니다. 실시간 API를 쓰는 `org_tables_v2.html`과 혼동하지 않도록 주의하세요.

## 생성 방법/입력
- 스크립트: `build_org_tables.py`
- 입력 DB: `salesmap_latest.db`(SQLite 스냅샷)
- 실행 예시: `python build_org_tables.py --output org_tables.html` (옵션은 `docs/org_tables_usage.md` 참고)
- API 호출 없음: 생성 시점의 DB 내용을 그대로 HTML에 내장한다.

## UI 레이아웃 (정적 3×3)
- 딜 있음/딜 없음 두 세트를 좌우로 배치. 각 세트는 3×3 스택(또는 3단)으로 People/Deal/메모 테이블을 구성한다.
- 상단: People 테이블(딜 있음/딜 없음 각각)
- 중간: Deal 테이블(딜 있음 세트만 의미 있음)
- 하단: People 메모(좌), Deal 메모(우)

## 상호작용/상태
- 상태 분리: `stateWith`(딜 있는 People), `stateWithout`(딜 없는 People)로 독립적으로 선택/렌더.
- People 행 클릭 → 해당 세트의 선택 인덱스 갱신 → Deal/메모 테이블 갱신.
- Deal 행 클릭(딜 있는 세트) → Deal 메모 테이블 갱신.
- 조직/People/Deal 이름 클릭 시 브레드크럼/선택이 반영되지만, 네트워크 요청은 발생하지 않는다(데이터는 모두 내장).

## 포맷 규칙
- 금액: 억 단위(1e8)로 나누어 소수 2자리 표기.
- 날짜: `YYYY-MM-DD` 포맷으로 표시(시간은 잘라냄).
- 텍스트: 메모 등 긴 텍스트는 미리보기 형태로 잘려 보여줄 수 있음(툴팁/타이틀로 전체 확인).

## 관련 파일
- 생성 스크립트: `build_org_tables.py`
- 결과 HTML: `org_tables.html`
- 사용 가이드/옵션: `docs/org_tables_usage.md`
- 변경 이력(정적 UI 개편): `docs/daily_progress.md` 참고
