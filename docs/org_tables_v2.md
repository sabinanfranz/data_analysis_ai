---
title: org_tables_v2 동작 정리 (FastAPI 기반)
last_synced: 2025-12-24
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
---

# org_tables_v2 동작 정리 (FastAPI 기반)

`org_tables_v2.html`는 정적 HTML+JS로 동작하지만, 데이터는 FastAPI 백엔드(`/dashboard/server`)가 제공하는 `/api` 엔드포인트에서 실시간으로 불러옵니다. 현재 구현된 흐름과 UI, 캐시, 오류 처리 방식을 상세히 정리합니다.

## 실행/접속 방법
- 백엔드: `uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload` 등으로 실행하면 `/api`가 열린다. DB는 루트의 `salesmap_latest.db`를 읽는다(`dashboard/server/database.py`의 `DB_PATH`).
- 프런트: `org_tables_v2.html`을 브라우저에서 연다.  
  - 파일을 직접 열면 `API_BASE`는 `http://localhost:8000/api`로 설정된다.  
  - 웹 서버를 통해 배포하면 현재 origin에 `/api`를 붙여 쓴다(예: `https://foo.com` → `https://foo.com/api`).
- 기본 회사 조회 제한은 200건(`ORG_LIMIT` 상수). 검색/규모 필터 조합으로 더 좁혀야 한다.

## 사용 중인 API 엔드포인트 (`dashboard/server/org_tables_api.py`)
- `GET /api/sizes`: 조직 규모(distinct) 목록.
- `GET /api/orgs`: 규모(`size`, 기본 전체) + 검색어(`search`) + 페이징(`limit` 기본 200, `offset`)로 조직 목록을 반환. 각 조직은 `id/name/size`, 팀/담당자 JSON도 포함.
- `GET /api/orgs/{org_id}`: 단일 조직 조회(랭킹 화면에서 사전 조회용).
- `GET /api/orgs/{org_id}/memos`: 회사 단위 메모(Deal/People 없이 조직만 연결된 메모).
- `GET /api/orgs/{org_id}/people?hasDeal=true|false|null`: 조직 내 People 리스트. `hasDeal` 파라미터로 딜 존재 여부 필터.
- `GET /api/people/{person_id}/deals`: 해당 People의 Deal 리스트. 계약 체결일 desc, 없으면 생성일 desc.
- `GET /api/people/{person_id}/memos`: People에 연결된 메모(Deal 미연결).
- `GET /api/deals/{deal_id}/memos`: Deal에 연결된 메모.
- `GET /api/rank/2025-deals`: 상태 `Won` + 계약 체결일 2025년인 딜을 회사별 총액/과정포맷 별로 집계한 데이터.
- `GET /api/orgs/{org_id}/won-summary`: 선택 조직의 People을 `소속 상위 조직` 기준으로 묶어 Won 딜 금액을 연도별(2023/2024/2025) 합산하고, 고객사 담당자/데이원 담당자 리스트를 함께 반환.
- `GET /api/rank/2025-deals-people`: 2025년 Won 딜이 있는 조직별로, 상위 조직/팀/사람 단위로 묶은 People+모든 딜(상태 무관) 데이터와 2025 Won 합계(내림차순)를 반환.
- `GET /api/rank/mismatched-deals`: 딜의 고객사(orgId)와 담당 People의 organizationId가 다른 경우를 탐지해 반환(규모 필터 포함, 연도/상태 제한 없음).
- `GET /api/rank/won-yearly-totals`: 기업 규모별 2023/2024/2025 Won 금액 합계.
- `GET /api/rank/won-industry-summary`: 기업 규모별 업종 구분(대) 단위로 2023/2024/2025 Won 금액을 합산하고 회사 수를 반환.

## 프런트 전역 상태/캐시 구조
- 주요 상태(`state`): 활성 메뉴(`activeMenuId`), 규모/검색어/회사 선택, 랭킹 필터, People/Deal/상위 조직 선택, 메모 목록, 모달 핸들, 랭킹 화면에서 넘어올 때 쓸 `pendingOrgId`/`pendingOrgFallback`, StatePath 포트폴리오 상태(`statepath2425`: segment/search/sort/limit/items/summary/loading/error).
- 캐시(`cache`): 조직별 회사 메모/People/Deal, People 메모, Deal 메모, 2025 랭킹, 조직 단건 조회(검색 결과에 없을 때 fallback용) 모두 `Map`으로 저장해 재요청을 줄인다. StatePath 포트폴리오(`statepathPortfolioByKey`: 세그먼트/검색/정렬 키)와 상세(`statePathByOrg`)도 Map 캐시로 추가했다. 캐시 무효화는 제공하지 않으므로 DB를 바꿨으면 새로고침 필요.
- 알림: `showToast`가 성공/에러 메시지를 하단 토스트로 3.2초간 노출.
- 메모 모달: 메모 행을 클릭하면 작성일/작성자/본문을 모달로 보여주며, ESC 또는 배경 클릭/닫기 버튼으로 닫는다.
- Salesmap 외부 링크: `SALESMAP_WORKSPACE_PATH` 상수로 워크스페이스 경로를 설정해 딜/People 링크를 Salesmap으로 연결한다(조직 뷰어 People 표, 2025 딜·People 표에서 이름 클릭 시 새 탭 이동).

## 메뉴/화면 구성
- 사이드바 메뉴(순서):
  - `2025 Top100 카운터파티 DRI`
  - `2025년 체결액 순위`
  - `조직/People/Deal 뷰어`(기본)
  - `교육 1팀 딜체크`
  - `교육 2팀 딜체크`
  - `StatePath 24→25`
  - `2025 대기업 딜·People`
  - `업종별 매출`
  - `고객사 불일치`
- 콘텐츠 영역은 메뉴별 렌더러가 채운다(`MENU_RENDERERS` → `renderContent`).

### 교육 딜체크 (org_tables_v2.html `renderDealCheckScreen`)
- 대상 데이터: `/api/deal-check?team=edu1|edu2` (SQL 딜 중 owners에 해당 팀 멤버 포함, personId/personName 포함). 레거시 `/api/deal-check/edu1`, `/api/deal-check/edu2`도 공통 엔진 호출.
- 컨테이너: 리텐션(2025 Won 금액 파싱>=0 조직) / 신규로 분리, 같은 정렬 적용.
- 정렬: orgWon2025Total DESC → createdAt ASC → dealId ASC.
- 컬럼: 기업명(세일즈맵 조직 링크, 15ch 고정) / 소속 상위 조직(15ch) / 팀(15ch) / 담당자(고객사, people 링크, 8ch 고정) / 생성날짜(YYMMDD) / 딜 이름(세일즈맵 딜 링크, 남는 폭 사용) / 과정포맷(동적 폭) / 파트(owners→PART_STRUCTURE 매핑) / 데이원(owners raw) / 가능성(리스트→"값1/값2") / 수주 예정일(YYMMDD) / 예상(금액 포맷) / 메모(버튼).
- 줄바꿈 정책: `.dealcheck-screen` 래퍼 하위 table/th/td/button에 `white-space: nowrap; word-break: keep-all; overflow-wrap: normal;` + ellipsis. 가로 스크롤 허용.
- 폭 정책: org/upper/team=15ch 고정, personName=8ch 고정, memo=버튼 폭 측정 기반(px, clamp 72~140), 그 외 동적(px) 측정, 딜 이름은 남는 폭 사용.
- 메모: memoCount>0 → `메모 확인` 활성 버튼, memoCount=0 → `메모 없음` 비활성 버튼(pointer-events:none). 모달은 ESC/X/오버레이로 닫힘, 날짜 YYMMDD, 메모 내용 `pre-wrap`, 내용 폰트 1.5em.
- 링크: 기업명/딜/담당자는 세일즈맵 새 탭 이동(SALESMAP_BASE, org/people/deal URL), 내부 navigateToOrg 사용 안 함.


### 조직/People/Deal 뷰어 흐름
1. 초기화(`initOrgScreen`)
   - API Base 라벨 표시.
   - 규모 드롭다운(`loadSizes`) → 기본 `대기업`, 없으면 첫 항목.
   - 검색어 입력/엔터/검색 버튼, 조직 선택 드롭다운, 선택 초기화 버튼 이벤트를 묶는다.
   - 랭킹 화면에서 넘어온 `pendingOrgId`가 있으면 `size="전체"`로 바꾸고 해당 조직을 우선 조회한다(검색어를 org id로 채워 목록을 좁힌 뒤, 검색 결과에 없으면 단건 조회 결과를 fallback으로 리스트에 삽입).
2. 조직 목록 로드(`loadOrgs`)
   - `/orgs`를 호출하면서 규모/검색어/limit=200/offset을 전달. People 또는 Deal이 1건 이상 있는 조직만 반환되며, 2025년 Won 금액 합계 내림차순 후 이름 순으로 정렬된다.
   - 로딩 중 회사 메모 힌트는 “회사 목록 불러오는 중...”으로 표시.
   - 이전 선택 조직이 목록에 있으면 유지, 없으면 선택 해제. `preselectOrgId`(랭킹 → 조직 이동 시)와 fallback 조직이 있으면 목록이 비어도 fallback을 1건으로 넣어 선택 후 상세 로드.
   - 0건이고 검색어가 비어 있으면 규모를 `전체`로 전환해 재조회한다. 자동으로 회사를 선택하지 않는다.
   - 실패 시 토스트 에러 + 조직 관련 뷰를 모두 비운다(`clearOrgViews`).
3. 조직 선택(`loadOrgDetail`)
   - 선택 시 People/Deal/상위 조직 선택 상태를 초기화하고, 아래 요청을 병렬 수행(캐시 우선): 회사 메모 `/orgs/{id}/memos`, People 전체 `/orgs/{id}/people`, 상위 조직 Won 합계 `/orgs/{id}/won-summary`.
   - 응답을 캐시에 저장 후 표 렌더. 선택된 조직 이름은 breadcrumb에 반영.
4. 상단 요약(소속 상위 조직별 Won 합계)
   - `GET /orgs/{orgId}/won-summary`로 `소속 상위 조직` 단위 그룹핑 후 Won 딜 금액을 계약 체결 연도별(2023/2024/2025)로 합산.
   - 금액은 `금액` 컬럼만 사용, `계약 체결일`이 2023/2024/2025가 아닌 경우는 합산하지 않음. `소속 상위 조직` 비어 있으면 `미입력`으로 묶음.
   - 고객사 담당자는 `팀/이름/직급/담당 교육 영역`을 줄바꿈으로 나열(중복 제거). 데이원 담당자는 Deal `담당자` JSON에서 이름/ID를 추출해 줄바꿈으로 나열(중복 제거).
   - 표 행 클릭 시 해당 상위 조직이 `selectedUpperOrg`로 설정되며, 아래 2×2 컨테이너(사람/딜/메모)가 해당 상위 조직 필터로 갱신된다. 선택 행은 `active`로 하이라이트.
5. 회사 메모 영역
   - 메모 수를 배지로 보여주고, 본문은 140자까지만 테이블에 노출(툴팁/모달로 전체 확인).
   - 선택된 회사가 없거나 메모가 한 건도 없으면 카드 자체를 표시하지 않는다.
6. 상위 조직 People/Deal 컨테이너(2×2)
   - 상단 왼쪽: 선택된 상위 조직에 속한 People 리스트(`이름/소속 상위 조직/팀(명함/메일서명)/직급(명함/메일서명)/담당 교육 영역`).
   - People 행 오른쪽에 `웹폼 내역` 버튼 추가: 해당 People의 웹폼 제출 내역(`won-groups-json`의 webforms)을 모달 내 테이블로 표시(날짜·제목). 날짜가 여러 개인 webform은 날짜별로 분리된 행으로 노출. 내역이 없으면 비활성화/“없음”.
   - 상단 오른쪽: 선택된 People의 Deal 리스트. 생성일/계약 체결일/금액·예상 금액(억 단위 변환), 담당자 이름을 보여준다. 상위 조직을 선택하면 첫 People과 첫 Deal을 자동 선택해 관련 메모를 불러온다.
   - 하단 왼쪽: 선택된 People 메모(`/people/{id}/memos`), 하단 오른쪽: 선택된 Deal 메모(`/deals/{id}/memos`). 선택이 없으면 비우고, 메모가 없으면 “메모가 없습니다.”를 단일 행으로 표시한다.
7. 선택 초기화 버튼
   - 규모/검색/회사 선택까지 기본값으로 리셋하고 목록을 재조회하며, 상위 조직/People/Deal/메모/Won 요약/JSON 상태를 모두 초기화한다. 리셋 후 회사는 자동 선택되지 않는다.
8. Breadcrumb
   - 조직/People/Deal 이름을 순서대로 표시. 선택이 없으면 `-`.
9. 상위 조직별 JSON(23/24/25 Won 기준)
   - 단일 카드 안에서 좌(전체)/우(선택 상위 조직) 영역으로 나누고, 각 영역에 `JSON 확인/복사`와 `간소화 JSON/복사` 버튼이 있다.
   - `/orgs/{id}/won-groups-json`과 `/orgs/{id}/won-groups-json-compact`를 모두 호출해 캐시 후 upper_org로 필터링한다. 회사/상위 조직이 바뀌면 모든 JSON 상태를 초기화하고 버튼을 비활성화한다.
   - JSON의 `organization` 블록에는 `id/name/size/industry` 외에 `industry_major`(업종 구분 대), `industry_mid`(업종 구분 중)도 포함된다. compact 버전은 `schema_version`·deal_defaults·summary 블록이 추가되고 memos/webforms가 제거된다.
   - 상위 조직이 선택되지 않았을 때는 “아래 표에서 소속 상위 조직을 선택해주세요” 안내와 함께 JSON 버튼이 비활성화된다. 선택하면 `선택된 상위 조직: …` 라벨이 표시된다.
10. StatePath
   - 회사 선택 후 `StatePath 보기` 버튼으로 `/api/orgs/{orgId}/statepath`를 호출해 2024/2025 상태, Path 이벤트, Seed, 추천을 모달로 표시한다.
   - 모달 구성: 연도별 요약(총액/온라인/오프라인/HRD/BU), 4셀 비교(2024 vs 2025), 이벤트 목록(seed 포함), RevOps 추천(다음 목표/타겟 셀/카운터파티 A/B/C/action play).
   - 금액은 API가 억 단위(amount_eok)로 내려주므로 `formatEok`(소수 2자리 + 억)로 표시한다. 캐시(`statePathByOrg`)로 재호출을 줄인다.

### 2025년 체결액 순위 화면
- 규모 필터: 상단 `기업 규모` 셀렉터로 `/rank/2025-deals?size=...`를 호출하며, 규모별로 별도 캐시(Map)에 저장한다. 기본은 `전체`.
- 표 컬럼: 순위, 회사, 2024 등급/총액, 24→25 배수, 2025 등급/총액, 2025 온라인/비온라인, 2026 목표액(배수 적용), 26 온라인/26 비온라인. 목표액은 grade별 배수(state.rankMultipliers) 또는 특정 회사(삼성전자 50억 하드코딩)로 계산하며, 온라인 금액은 그대로 더하고 배수는 비온라인 금액에만 곱한다.
- 요약 표: 드롭다운과 무관하게 기업 규모별 2025 합계/온라인/비온라인, 2026 목표액/26 온라인/26 비온라인을 표로 표시하며 삼성전자는 합산에서 제외된다(캐시된 각 규모 데이터를 활용).
- 등급 가이드/배수 모달: 등급 구간 표를 열람하고 등급별 배수를 입력·적용할 수 있다.
- 회사 이름 클릭 시 `navigateToOrg`를 통해 조직/People/Deal 화면으로 이동: 메뉴를 전환하고, `size="전체"` + 검색어를 org id로 세팅한 뒤 해당 조직을 우선 로드한다(단건 조회 fallback 포함).

### 2025 Top100 카운터파티 DRI 화면
- 데이터: `/rank/2025-top100-counterparty-dri?size=...&limit=100&offset=...`(기본 대기업, limit 100 단위) 호출 후 캐시(Map) 저장. 온라인=구독제(온라인)/선택구매(온라인)/포팅(완전 일치), 그 외 비온라인. upper_org/owners 공백은 `미입력`으로 정규화.
- 표 컬럼: 기업명, 티어, 25년 체결액, 카운터파티명, 25 온라인, 25 비온라인, 25 담당자(한 줄 · ellipsis), 팀&파트, DRI(O/X). DRI/팀&파트는 PART_STRUCTURE 기반 프런트 계산(단일 팀·파트(셀 제외)만 O). 카운터파티 총액은 정렬에만 사용하며 표시하지 않는다.
- 정렬: 기업 25 총액 내림차순 → 카운터파티 25 총액 내림차순. 목록 상단에 org 페이지 Prev/Next(100개 단위) 버튼으로 다음 상위 조직 집합을 불러온다. 테이블 자체의 행 페이지네이션은 없음.
- 행 클릭 시 상세: 선택 org/upper_org의 won-groups-json/people를 사용해 팀별 25 온라인·비온라인 합계/딜 목록, People 리스트(웹폼 버튼 포함)를 모달(xl)로 표시한다. 모달 상단에 25 담당자/팀&파트/DRI를 강조해 보여준다. 캐시 무효화 없음 문구를 상단에 노출.

### 2025 대기업 딜·People 화면
- 데이터: `/rank/2025-deals-people?size=...`로 2025 Won 딜 보유 조직을 불러오며, People별로 연결된 모든 딜(상태 무관)을 함께 제공한다. 상위 조직과 팀이 모두 `미입력`일 때만 제외(상위 조직이 미입력이라도 팀이 있으면 표시).
- 필터: 규모 기본 `대기업`, 회사/상위 조직 텍스트 필터, 리셋 버튼으로 초기화.
- 표: 회사/상위 조직/팀/이름/직급/교육 영역/2025 Won(억)/딜 수/딜 보기 버튼. 딜 보기 클릭 시 모달에서 생성일·딜 이름·상태·금액(억)·계약일·과정포맷 목록을 표시. 회사명 클릭 시 조직 뷰어로 이동, 이름 클릭 시 Salesmap People 링크로 새 탭 이동.

### 고객사 불일치 화면
- 데이터: `/rank/mismatched-deals?size=...`로 딜의 organizationId와 People.organizationId가 다른 레코드를 조회(연도/상태 제한 없음), 규모별 캐시.
- 표: 회사(딜 기준)/People 조직/People 이름/딜 이름/상태/계약일/금액/과정포맷/과정 형태. 회사명 클릭 시 조직 뷰어로 이동, 딜/People 이름은 Salesmap 워크스페이스 링크로 이동.

### 업종별 매출 화면(메뉴 2번)
- 대기업/중견기업 각각에 대해 업종 구분(대)별 2023/2024/2025 Won 금액과 회사 수를 한 표로 표시한다.
- 컬럼: `업종 구분(대)`, `2023 Won(억)`, `2024 Won(억)`, `2025 Won(억)`, `회사 수`.
- 데이터 소스: `/rank/won-industry-summary?size=대기업|중견기업` (백엔드에서 연도별 Won 합계와 회사 수 집계).
- 오류/빈 데이터 시 표 대신 안내 문구를 노출하고 토스트로 에러를 표시한다.

### StatePath 24→25 포트폴리오 화면
- 세그먼트 탭(전체/대기업/중견/중소/공공/대학교/기타·미입력) + 검색 + 정렬(2025 desc/Δ desc/name asc) 컨트롤이 상단에 노출된다.
- `/api/statepath/portfolio-2425`를 호출해 2024/2025 회사 총액(억)과 버킷을 받아 테이블에 표시한다. 키 `{segment, search, sort, limit}` 조합별로 `statepathPortfolioByKey`에 캐싱한다.
- 행 클릭 시 기존 StatePath 모달을 재사용해 `/api/orgs/{id}/statepath` 응답(2024/2025 state + path 이벤트/seed/추천)을 표시한다. 상세 응답은 `statePathByOrg` 캐시를 그대로 사용한다.
- 하단에 “DB 교체 시 새로고침 필요(캐시 무효화 없음)” 안내 문구를 함께 노출한다.
- V1/V2 추가 UX:
  - Snapshot 카드(계정수/24·25 합계/Δ/Company 변화/OPEN·RISK), 퀵필터 칩(Risk/Open/ScaleUp/Company ↑↓=/Seed/Online·Offline Shift), Pattern Explorer(Company 전이 매트릭스, 4셀 이벤트 매트릭스, Rail 변화 요약), Top Patterns 5줄(OPEN/CLOSE/UP/DOWN/Seed) 렌더 및 클릭 필터 적용.
  - Breadcrumb: 현재 세그먼트/검색/퀵필터/패턴 필터를 토큰으로 표시, x로 개별 해제, “전체 해제” 버튼 제공.
  - 세그먼트 비교 테이블: segment=전체 + 검색/필터 기본값일 때만 표시, 세그먼트별 계정수·2025총액·비율(Company↑/OPEN/Risk/H→B)을 보여주며 행 클릭 시 해당 세그먼트로 전환 후 필터 초기화.
  - 테이블 페이징: 기본 pageSize=200, Prev/Next 버튼. summary/매트릭스는 filteredItems 전체로 계산(정확성 유지).
  - 용어/기준 안내: STATEPATH_GLOSSARY 기반 툴팁/title, 섹션별 ⓘ 버튼, 통합 “용어/기준” 모달을 제공해 Snapshot/QuickFilters/Pattern/SegmentComparison/TopPatterns/Breadcrumb/Pagination/버킷 정의를 확인할 수 있다.
  - JSON 내보내기: Accounts Table 섹션에서 현재 필터 결과 전체를 JSON(메타+행)으로 보기/복사할 수 있고, StatePath 상세 모달에서 RevOps 추천을 제외한 Core JSON을 복사할 수 있다(툴팁/legend에 기준 설명 포함).

## 예외/UX 처리
- API 실패 시 토스트로 원인 메시지 표시, 관련 표는 비워진다.
- 회사가 선택되지 않은 상태에서 표를 클릭해도 아무 동작을 하지 않으며 힌트 문구로 안내.
- 캐시는 새 DB로 교체해도 자동 무효화되지 않으므로, 백엔드가 최신 DB를 읽도록 한 뒤 브라우저 새로고침이 필요하다.

## 개발/테스트 팁
- 의존성: `requirements.txt`(FastAPI, pandas 등) + 개발용 `pytest`(로컬 venv 설치).  
  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/pip install pytest
  ```
- 테스트 실행: 소스 루트 기준 `PYTHONPATH=.`로 실행해야 모듈을 찾는다.  
  ```bash
  PYTHONPATH=. .venv/bin/pytest -q
  ```

## Verification
- 사이드바 메뉴가 순서대로 `2025 Top100 카운터파티 DRI` → `2025년 체결액 순위` → `조직/People/Deal 뷰어` → `교육 1팀 딜체크` → `교육 2팀 딜체크` → `StatePath 24→25` → … 로 노출되는지 확인한다.
- 교육 1·2팀 딜체크 테이블에서 orgWon2025Total DESC → createdAt ASC → dealId ASC 정렬, 리텐션/신규 분리, nowrap/keep-all + colgroup 폭(15ch/8ch/동적/딜이름 남는 폭/메모 버튼 폭) 규칙이 적용되는지 DevTools로 확인한다.
- 교육 1팀 메모 버튼이 memoCount=0일 때 `메모 없음` 비활성 버튼(pointer-events none), memoCount>0일 때 `메모 확인` 활성 버튼으로 표시되고 모달이 ESC/X/오버레이로 닫히는지 확인한다.
- 가능성 컬럼이 배열을 "/"로 조인해 한 줄로 표시되고 날짜가 `YYMMDD`, 예상 금액이 `formatAmount`(억)로 렌더되는지 확인한다.
- 조직/People/Deal 뷰어에서 조직 목록이 2025 Won desc → 이름 asc로 정렬되고 People/Deal 없는 조직이 제외되는지 확인한다.
- 상위 조직 JSON/compact 버튼이 선택 여부에 따라 비활성/활성으로 변하며, 필터된 JSON이 upper_org 기준으로만 그룹을 남기는지 확인한다.
- StatePath 보기/포트폴리오 화면에서 금액이 억 단위 그대로 표시되고 segment/search/정렬/패턴 필터가 모두 반영되는지 확인한다.
