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
- 주요 상태(`state`): 활성 메뉴(`activeMenuId`), 규모/검색어/회사 선택, 랭킹 필터, People/Deal/상위 조직 선택, 메모 목록, 모달 핸들, 랭킹 화면에서 넘어올 때 쓸 `pendingOrgId`/`pendingOrgFallback`.
- 캐시(`cache`): 조직별 회사 메모/People/Deal, People 메모, Deal 메모, 2025 랭킹, 조직 단건 조회(검색 결과에 없을 때 fallback용) 모두 `Map`으로 저장해 재요청을 줄인다. 캐시 무효화는 제공하지 않으므로 DB를 바꿨으면 새로고침 필요.
- 알림: `showToast`가 성공/에러 메시지를 하단 토스트로 3.2초간 노출.
- 메모 모달: 메모 행을 클릭하면 작성일/작성자/본문을 모달로 보여주며, ESC 또는 배경 클릭/닫기 버튼으로 닫는다.
- Salesmap 외부 링크: `SALESMAP_WORKSPACE_PATH` 상수로 워크스페이스 경로를 설정해 딜/People 링크를 Salesmap으로 연결한다.

## 메뉴/화면 구성
- 사이드바 메뉴:  
  - `조직/People/Deal 뷰어`(기본)
  - `2025년 체결액 순위` (Won 2025)
  - `2025 대기업 딜·People` (2025 Won 딜이 있는 조직별 People 그룹, 딜은 상태 무관 전체 표시)
  - `고객사 불일치` (딜 orgId와 People.organizationId가 다른 경우 탐지)
- 콘텐츠 영역은 메뉴별 렌더러가 채운다(`menuConfig` → `renderContent`).

### 조직/People/Deal 뷰어 흐름
1. 초기화(`initOrgScreen`)
   - API Base 라벨 표시.
   - 규모 드롭다운(`loadSizes`) → 기본 `대기업`, 없으면 첫 항목.
   - 검색어 입력/엔터/검색 버튼, 조직 선택 드롭다운, 선택 초기화 버튼 이벤트를 묶는다.
   - 랭킹 화면에서 넘어온 `pendingOrgId`가 있으면 `size="전체"`로 바꾸고 해당 조직을 우선 조회한다(검색어를 org id로 채워 목록을 좁힌 뒤, 검색 결과에 없으면 단건 조회 결과를 fallback으로 리스트에 삽입).
2. 조직 목록 로드(`loadOrgs`)
   - `/orgs`를 호출하면서 규모/검색어/limit=200/offset을 전달.
   - 로딩 중 회사 메모 힌트는 “회사 목록 불러오는 중...”으로 표시.
   - 이전 선택 조직이 목록에 있으면 유지, 없으면 선택 해제. `preselectOrgId`(랭킹 → 조직 이동 시)와 fallback 조직이 있으면 목록이 비어도 fallback을 1건으로 넣어 선택 후 상세 로드.
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
   - 상단 오른쪽: 선택된 People의 Deal 리스트. 생성일/계약 체결일/금액·예상 금액(억 단위 변환), 담당자 이름을 보여준다. 첫 로드 시 첫 Deal을 자동 선택해 메모를 가져온다.
   - 하단 왼쪽: 선택된 People 메모(`/people/{id}/memos`), 하단 오른쪽: 선택된 Deal 메모(`/deals/{id}/memos`). 선택이 없으면 비우고, 메모가 없으면 “메모가 없습니다.”를 단일 행으로 표시한다.
7. 선택 초기화 버튼
   - 규모/검색/회사 선택까지 기본값으로 리셋하고 목록을 재조회하며, 상위 조직/People/Deal/메모/Won 요약/JSON 상태를 모두 초기화한다.
8. Breadcrumb
   - 조직/People/Deal 이름을 순서대로 표시. 선택이 없으면 `-`.
9. 상위 조직별 JSON(23/24/25 Won 기준)
   - 단일 카드 안에서 좌(전체)/우(선택 상위 조직) 영역으로 나누고, 각 영역에 `JSON 확인`/`JSON 복사` 버튼을 둔다.
   - 버튼 클릭 시 모달로 JSON을 열람하며, 표시할 데이터가 없으면 비활성화/토스트 안내. `/orgs/{id}/won-groups-json` 응답을 프런트에서 upper_org로 필터링해 사용한다.

### 2025년 체결액 순위 화면
- 규모 필터: 상단 `기업 규모` 셀렉터로 `/rank/2025-deals?size=...`를 호출하며, 규모별로 별도 캐시(Map)에 저장한다. 기본은 `전체`.
- 표 컬럼: 순위(클라이언트에서 index+1), 회사, 업종 구분(대), 업종 구분(중), 총액(억 단위 변환), 과정포맷. 과정포맷 셀 클릭 시 과정별 금액 목록을 메모 모달 형태로 표시.
- 회사 이름 클릭 시 `navigateToOrg`를 통해 조직/People/Deal 화면으로 이동: 메뉴를 전환하고, `size="전체"` + 검색어를 org id로 세팅한 뒤 해당 조직을 우선 로드한다(단건 조회 fallback 포함).

### 2025 대기업 딜·People 화면
- 데이터: `/rank/2025-deals-people?size=...`로 2025 Won 딜 보유 조직을 불러오며, People별로 연결된 모든 딜(상태 무관)을 함께 제공한다. 상위 조직/팀이 `미입력`인 행은 제외.
- 필터: 규모 기본 `대기업`, 회사/상위 조직 텍스트 필터, 리셋 버튼으로 초기화.
- 표: 회사/상위 조직/팀/이름/직급/교육 영역/2025 Won(억)/딜 수/딜 보기 버튼. 딜 보기 클릭 시 모달에서 생성일·딜 이름·상태·금액(억)·계약일·과정포맷 목록을 표시. 회사명 클릭 시 조직 뷰어로 이동.

### 고객사 불일치 화면
- 데이터: `/rank/mismatched-deals?size=...`로 딜의 organizationId와 People.organizationId가 다른 레코드를 조회(연도/상태 제한 없음), 규모별 캐시.
- 표: 회사(딜 기준)/People 조직/People 이름/딜 이름/상태/계약일/금액/과정포맷/과정 형태. 회사명 클릭 시 조직 뷰어로 이동, 딜/People 이름은 Salesmap 워크스페이스 링크로 이동.

### 업종별 매출 화면(메뉴 2번)
- 대기업/중견기업 각각에 대해 업종 구분(대)별 2023/2024/2025 Won 금액과 회사 수를 한 표로 표시한다.
- 컬럼: `업종 구분(대)`, `2023 Won(억)`, `2024 Won(억)`, `2025 Won(억)`, `회사 수`.
- 데이터 소스: `/rank/won-industry-summary?size=대기업|중견기업` (백엔드에서 연도별 Won 합계와 회사 수 집계).
- 오류/빈 데이터 시 표 대신 안내 문구를 노출하고 토스트로 에러를 표시한다.

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
