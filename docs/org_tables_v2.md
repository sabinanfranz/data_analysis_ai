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

## 프런트 전역 상태/캐시 구조
- 주요 상태(`state`): 활성 메뉴(`activeMenuId`), 선택 규모(`size`, 기본 `대기업`), 검색어, 조직 목록/선택, People/Deal 선택(딜 있음/없음 세트 분리), 메모 목록, 모달 핸들, 랭킹 화면에서 넘어올 때 쓸 `pendingOrgId`/`pendingOrgFallback`.
- 캐시(`cache`): 조직별 회사 메모/People(with/without)/Deal, People 메모, Deal 메모, 2025 랭킹, 조직 단건 조회(검색 결과에 없을 때 fallback용) 모두 `Map`으로 저장해 재요청을 줄인다. 캐시 무효화는 제공하지 않으므로 DB를 바꿨으면 새로고침 필요.
- 알림: `showToast`가 성공/에러 메시지를 하단 토스트로 3.2초간 노출.
- 메모 모달: 메모 행을 클릭하면 작성일/작성자/본문을 모달로 보여주며, ESC 또는 배경 클릭/닫기 버튼으로 닫는다.

## 메뉴/화면 구성
- 사이드바 메뉴:  
  - `조직/People/Deal 뷰어`(기본)  
  - `2025년 체결액 순위`
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
   - 선택 시 People/Deal 선택 상태를 초기화하고, 아래 3개 요청을 병렬 수행(캐시 우선): 회사 메모 `/orgs/{id}/memos`, People(딜 있음) `/people?hasDeal=true`, People(딜 없음) `/people?hasDeal=false`.
   - 응답을 캐시에 저장 후 표 렌더. 선택된 조직 이름은 breadcrumb에 반영.
4. 상단 요약(소속 상위 조직별 Won 합계)
   - `GET /orgs/{orgId}/won-summary`로 `소속 상위 조직` 단위 그룹핑 후 Won 딜 금액을 계약 체결 연도별(2023/2024/2025)로 합산.
   - 금액은 `금액` 컬럼만 사용, `계약 체결일`이 2023/2024/2025가 아닌 경우는 합산하지 않음. `소속 상위 조직` 비어 있으면 `미입력`으로 묶음.
   - 고객사 담당자는 `팀/이름/직급/담당 교육 영역`을 줄바꿈으로 나열(중복 제거). 데이원 담당자는 Deal `담당자` JSON에서 이름/ID를 추출해 줄바꿈으로 나열(중복 제거).
5. 회사 메모 영역
   - 메모 수를 배지로 보여주고, 본문은 140자까지만 테이블에 노출(툴팁/모달로 전체 확인).
   - 선택된 회사가 없거나 메모가 한 건도 없으면 카드 자체를 표시하지 않는다.
6. People (딜 있음/없음) 표
   - 각 표는 `이름/소속 상위 조직/팀(명함/메일서명)/직급(명함/메일서명)/담당 교육 영역` 컬럼을 표시하며, DB 정렬 순서 그대로(`ORDER BY name`).
   - 행 클릭 시 해당 세트의 People을 선택하고 Deal/People 메모를 불러온다. 선택 행은 `active`로 하이라이트.
7. Deal 표
   - 선택된 People이 없으면 힌트, 있으면 `/people/{id}/deals` 결과를 표시. 생성일/계약 체결일/금액·예상 금액(억 단위 변환), 담당자 이름을 보여준다.
   - Deal 목록을 처음 로드하면 첫 번째 Deal을 자동 선택하고 Deal 메모를 가져온다. 다른 Deal 클릭 시 선택/메모만 바뀐다.
   - 계약 체결일이 있는 Deal이 앞쪽에 오도록 정렬(계약 체결일 DESC → 생성일 DESC).
8. 메모 표(people/deal)
   - 부모(선택된 People/Deal)가 없으면 비움. 메모가 없으면 “메모가 없습니다.” 단일 행만 렌더.
   - 각 메모 행을 클릭하면 모달로 전체 내용을 확인할 수 있다.
9. 선택 초기화 버튼
   - People/Deal 선택과 관련 메모/Deal 표를 모두 초기화하되, 조직/검색/규모 선택은 유지한다.
10. Breadcrumb
   - 조직/People/Deal 이름을 순서대로 표시. 선택이 없으면 `-`.

### 2025년 체결액 순위 화면
- `/rank/2025-deals`를 최초 1회 호출하여 캐시에 저장, 이후 재방문 시 캐시 사용.
- 표 컬럼: 순위(클라이언트에서 index+1), 회사, 총액(억 단위 변환), 과정포맷. 과정포맷 셀 클릭 시 과정별 금액 목록을 메모 모달 형태로 표시.
- 회사 이름 클릭 시 `navigateToOrg`를 통해 조직/People/Deal 화면으로 이동: 메뉴를 전환하고, `size="전체"` + 검색어를 org id로 세팅한 뒤 해당 조직을 우선 로드한다(단건 조회 fallback 포함).

## 예외/UX 처리
- API 실패 시 토스트로 원인 메시지 표시, 관련 표는 비워진다.
- 회사가 선택되지 않은 상태에서 표를 클릭해도 아무 동작을 하지 않으며 힌트 문구로 안내.
- 캐시는 새 DB로 교체해도 자동 무효화되지 않으므로, 백엔드가 최신 DB를 읽도록 한 뒤 브라우저 새로고침이 필요하다.
