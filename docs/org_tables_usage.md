# Org Tables Explorer 사용 가이드

> FastAPI 기반 실시간 뷰어인 `org_tables_v2.html`의 동작/구조는 `docs/org_tables_v2.md`를 참고하세요. 이 문서는 정적 HTML을 생성하는 `build_org_tables.py` 버전(`org_tables.html`)만 다룹니다.

## 생성 방법
- 기본 DB: `salesmap_latest.db`를 사용합니다.  
  ```bash
  python3 build_org_tables.py --output org_tables.html
  ```
- 다른 DB를 지정하려면 `--db-path`에 경로를 전달합니다.

## UI 구성
- 상단 헤더: `기업 규모` 드롭다운(기본 `대기업`, 없으면 `전체`), 회사 선택 드롭다운, `선택 초기화` 버튼.
- 본문 3×3 그리드
  - **왼쪽 컬럼(행 1~3 전체)**: 선택된 회사의 회사 메모.
  - **중앙 컬럼(딜 있음 세트)**: 1행 `People (딜 있음)` 테이블 → 2행 선택된 사람의 `Deal` 테이블 → 3행 People 메모(상) + Deal 메모(하).
  - **오른쪽 컬럼(딜 없음 세트)**: 중앙과 동일 구조지만 딜 없는 People 기준.

## 동작 방식
- 기업 규모 선택 → 해당 규모의 회사만 회사 드롭다운에 표시.
- 회사 선택 → People/Deal/메모 모든 표 리셋 후 해당 회사 데이터로 렌더.
- People 행 클릭 → 해당 세트(딜 있음/없음)의 Deal, People 메모 갱신.
- Deal 행 클릭 → 해당 세트의 Deal 메모 갱신.
- 회사 메모는 회사 선택 시 자동 갱신.
- 금액 포맷: `(값 / 1e8).toFixed(2) + '억'`, 날짜 포맷: 문자열에서 날짜 부분만 `YYYY-MM-DD` 추출.
- 선택 초기화: 두 세트(stateWith/stateWithout)의 personId/dealId를 모두 해제 후 표 재렌더.

## 파일 및 스크립트 위치
- 생성 스크립트: `build_org_tables.py`
- 생성된 HTML: `org_tables.html` (명령 실행 위치에 생성)
