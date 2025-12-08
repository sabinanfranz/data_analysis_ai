# Org Tables Explorer 사용 가이드

`build_org_tables.py`가 생성하는 `org_tables.html`의 데이터 흐름과 UI 사용법을 정리합니다.

## 생성 방법
- 기본 DB: `salesmap_latest.db`를 사용합니다.  
  ```bash
  python3 build_org_tables.py --output org_tables.html
  ```
- 다른 DB를 지정하려면 `--db-path`에 경로를 전달합니다.
- 유저/팀 API를 함께 쓰려면 Base URL/토큰을 넘깁니다(없으면 HTML 내 입력창에 직접 입력할 수 있습니다).
  ```bash
  API_BASE_URL=https://api.example.com API_TOKEN=xxx \
    python3 build_org_tables.py --output org_tables.html
  ```
  - CLI 옵션: `--api-base-url`, `--api-token` (env `API_BASE_URL`, `API_TOKEN`도 인식)

## UI 구성
- 상단 헤더
  - `기업 규모` 드롭다운(기본 `대기업`, 미존재 시 `전체`), 회사 선택 드롭다운, `선택 초기화` 버튼.
  - API 컨트롤: Base URL, Bearer 토큰 입력, `유저/팀 새로고침` 버튼, 상태 배지.
- 상단 컨테이너: 회사에 직접 연결된 메모(organizationId만 있고 peopleId/dealId가 없는 메모). 메모가 없으면 낮은 높이, 있으면 중단/하단 컨테이너의 약 절반 높이로 확장.
- API 컨테이너: 유저/팀 목록 표(성공 시 팀 구성원 이름도 유저 데이터와 매핑해 표시).
- 중단 컨테이너(딜 있는 People):
  - 좌: `People (딜 있음)` 테이블(딜 개수 표시).
  - 중: 선택된 사람의 `Deal` 테이블(금액/예상 체결액 억 단위, 날짜는 YYYY-MM-DD).
  - 우: `People 메모`(위) + `Deal 메모`(아래) 스택.
- 하단 컨테이너(딜 없는 People): 중단과 동일 구조지만 `People (딜 없음)` 기준.

## 동작 방식
- 기업 규모 선택 → 해당 규모의 회사만 회사 드롭다운에 표시.
- 회사 선택 → People/Deal/메모 모든 표 리셋 후 해당 회사 데이터로 렌더.
- `유저/팀 새로고침` → `/v2/user`, `/v2/team` 병렬 호출 후 표 렌더. Base URL/토큰이 없으면 오류 배지로 안내.
- People 행 클릭 → 해당 세트(딜 있음/없음)의 Deal, People 메모 갱신.
- Deal 행 클릭 → 해당 세트의 Deal 메모 갱신.
- 회사 메모는 회사 선택 시 자동 갱신.
- 금액 포맷: `(값 / 1e8).toFixed(2) + '억'`, 날짜 포맷: 문자열에서 날짜 부분만 `YYYY-MM-DD` 추출.
- 선택 초기화: 두 세트(stateWith/stateWithout)의 personId/dealId를 모두 해제 후 표 재렌더.

## 파일 및 스크립트 위치
- 생성 스크립트: `build_org_tables.py`
- 생성된 HTML: `org_tables.html` (명령 실행 위치에 생성)
