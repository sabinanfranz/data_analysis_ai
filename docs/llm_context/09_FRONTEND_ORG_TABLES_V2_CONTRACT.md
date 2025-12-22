# org_tables_v2 프런트 계약

## 1) 실행/접속
- 정적 HTML(`org_tables_v2.html`)을 브라우저에서 직접 열거나 간단한 정적 서버(`python -m http.server`)로 제공.
- API_BASE 결정: `window.location.origin`이 유효하면 `origin + "/api"`를 사용, 아니면 기본 `http://localhost:8000/api`.
- 세일즈맵 링크: `SALESMAP_WORKSPACE_PATH` 상수로 workspace id를 설정.

## 2) 전역 state 구조(주요 필드)
- `activeMenuId`: 현재 메뉴 id (`org-view`, `rank-2025`, `rank-2025-people`, `rank-2025-counterparty-dri`, `mismatch-2025`, `industry-2025`, `statepath-2425`).
- `size`, `rankSize`, `rankPeopleSize`, `mismatchSize`: 규모 필터.
- `rankPeopleOrgFilter`, `rankPeopleUpperFilter`: 텍스트 필터.
- `orgs`, `orgSearch`, `selectedOrg`, `selectedUpperOrg`, `selectedPerson`, `selectedDeal`.
- 데이터 보관: `people`, `deals`, `orgMemos`, `personMemos`, `dealMemos`, `wonSummary`, `wonGroupJson/Compact`, `filteredWonGroupJson/Compact`.
- StatePath 전용: `statepath2425`(segment/search/sort/limit/offset/items/filteredItems/summary/loading/error + quickFilters + patternFilter + breadcrumb + pagination)와 `statepathLegend`(용어 모달 open/section).
- 2025 카운터파티 DRI 전용: `rankCounterpartyDri`(size/rows/loading/error/selected/detail/search/dri/hideMissingUpper/sort/teamPart/teamPartOptions).
- 모달 상태: `modal`(메모), `jsonModal`, `webformModal`, `rankPeopleModal`(딜 리스트), `rankGuideModal`, `rankMultiplierModal`, `statePathModal`(단건 statepath), `statePathLegendModal`.
- 캐시: 별도 `cache` 객체(Map)로 관리(아래 참조).
- 디버그: `DEBUG_ORG_SELECT`/`setOrgSelectDebug`로 조직 선택 디버그 로그 제어.

## 3) cache 구조/정책
- Map 캐시: `orgLookup`, `orgMemos`, `peopleByOrg`, `deals`, `personMemos`, `dealMemos`, `wonSummary`, `wonGroupJsonByOrg`, `wonGroupJsonCompactByOrg`, `rank2025BySize`, `rank2025PeopleBySize`, `rank2025CounterpartyDriBySize`, `mismatch2025BySize`, `statepathPortfolioByKey`, `statePathByOrg`, `statepathDetailByOrg`(2425 상세).
- 무효화 없음: 새 DB로 교체 시 브라우저 새로고침 필요.
- 캐시 적중 시 API 호출을 건너뛰고 즉시 렌더.

## 4) 핵심 사용자 플로우
1. 조직 목록 로드: `/api/orgs` 호출(규모/검색/limit=200/offset). People/Deal이 1건 이상 있는 조직만, 2025 Won desc 정렬. 결과 0건 + 검색어 없음 → 규모를 `전체`로 바꿔 재조회. 자동 선택 없음.
2. 조직 선택: 드롭다운 선택 시 `loadOrgDetail` → `/orgs/{id}/memos`, `/orgs/{id}/people`, `/orgs/{id}/won-summary` 병렬 호출 → 상태/표 갱신.
3. 상위 조직 선택: Won 요약 표 행 클릭 → `selectedUpperOrg` 설정 → People/Deal/메모 표를 상위 조직 필터로 렌더. Won 그룹 JSON/compact도 필터(`filterWonGroupByUpper`). 선택 시 첫 People/첫 Deal을 자동 선택해 메모까지 로드한다.
4. People 선택: People 행 클릭 → Deals fetch(`/people/{id}/deals`) → Deal 메모 fetch(`/deals/{id}/memos`) → 관련 표/모달 갱신.
5. JSON 버튼: `/orgs/{id}/won-groups-json`·`won-groups-json-compact`를 캐시 후 전체/선택 상위 조직 JSON/compact 모달/복사. 선택 없으면 버튼 비활성화 + 안내 문구.
6. 선택 초기화: 규모/검색/회사 선택 상태를 기본으로 리셋하고 목록 재조회. 상위 조직/People/Deal/메모/Won 요약/JSON 상태도 초기화한다. 자동 선택 없음.

## 5) 메뉴별 동작 요약
- **조직/People/Deal 뷰어(`org-view`)**: 조직 목록/메모/People/Deal/메모, 상위 조직 Won 요약(2025 담당자/팀&파트/DRI 포함), 상위 조직별 JSON + 간소화 JSON, StatePath 버튼/모달, 웹폼 내역 모달(People 행 버튼), 딜/People 세일즈맵 링크.
- **2025년 체결액 순위(`rank-2025`)**: `/api/rank/2025-deals` 호출, 규모 필터, 등급 가이드/배수 모달. 표는 24/25년 등급·총액, 24→25 배수, 25년 온라인/비온라인, 26년 목표액을 표시하며 별도 요약 카드는 없다. 회사 클릭 시 조직 화면으로 이동.
- **2025 대기업 딜·People(`rank-2025-people`)**: `/api/rank/2025-deals-people`, 규모/회사/상위 조직 필터, 딜 보기 모달.
- **2025 Top100 카운터파티 DRI(`rank-2025-counterparty-dri`)**: `/api/rank/2025-top100-counterparty-dri?size=...&limit=100&offset=...` 호출. 온라인=구독제(온라인)/선택구매(온라인)/포팅, owners/upper_org 미입력은 `미입력` 정규화. 팀&파트/DRI는 PART_STRUCTURE 기반 프런트 계산(단일 팀·파트면 O, ‘셀’ 포함도 허용). 필터: 검색, DRI, 팀&파트 드롭다운, 미입력 상위 조직 숨김, 정렬, 규모. 회사명 클릭 시 조직/People/Deal 뷰어로 이동해 해당 회사 검색, 나머지 영역 클릭 시 모달을 열어 25 비온라인·26 타겟·26 비온라인 체결 소스 딜을 표로 보여준다(금액→예상체결액 폴백, 계약체결일→수주예정일 연도 판정, 성사가능성 “높음/확정”이면 집계, 2025 딜이라도 수강시작 2026이면 26 체결로 가산). Org 100개 단위 Prev/Next로 다음 상위 조직 묶음을 조회한다.
- **고객사 불일치(`mismatch-2025`)**: `/api/rank/mismatched-deals`, 규모 필터, 딜 org vs People org 비교.
- **업종별 매출(`industry-2025`)**: `/api/rank/won-industry-summary`, 업종 구분(대)별 23/24/25 Won 합계/회사 수 표시.

## 6) UX 정책
- 토스트: 성공/정보/에러 메시지를 하단에 3.2초 노출.
- 모달: 메모/JSON/웹폼/딜 보기/StatePath/StatePath 용어(legend) 모달. ESC, 닫기 버튼, 배경 클릭으로 닫힘(legend는 섹션 라벨 표시).
- 버튼 비활성화: 데이터 없는 상태에서 JSON 보기/복사, 웹폼 내역(없으면 “없음”), 조직 미선택 시 People/Deal 표 비움, 상위 조직 미선택 시 관련 표/버튼 비활성화.
- 선택 표시: 선택된 행은 `active` 클래스, 상위 조직 라벨/브레드크럼에 선택 상태 반영.
- Won 요약 DRI 규칙: 2025 Won 딜 담당자 이름 → PART_STRUCTURE 매핑, 단일 팀/파트면 `O`(셀 포함 허용), 매핑 실패나 복수 콤보면 `X`.
- StatePath 모달: `/api/orgs/{id}/statepath` 응답을 캐시(`statePathByOrg`) 후 연도별 요약/셀 비교/이벤트/추천 블록으로 렌더, 금액은 억 단위 그대로 표시(`formatEok`). StatePath 화면에는 STATEPATH_GLOSSARY 기반 툴팁/title/ⓘ 버튼과 통합 “용어/기준” 모달이 붙어 있다.
- StatePath JSON 내보내기: Accounts Table 섹션에서 필터 결과 전체(filteredItems)를 메타+행 JSON으로 보기/복사할 수 있고, StatePath 상세 모달에서 RevOps 추천을 제외한 Core JSON을 복사할 수 있다(툴팁/legend에 기준 명시, 클립보드 실패 시 textarea 폴백).
