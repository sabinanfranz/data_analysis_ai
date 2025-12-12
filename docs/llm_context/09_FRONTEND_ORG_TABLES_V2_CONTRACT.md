# org_tables_v2 프런트 계약

## 1) 실행/접속
- 정적 HTML(`org_tables_v2.html`)을 브라우저에서 직접 열거나 간단한 정적 서버(`python -m http.server`)로 제공.
- API_BASE 결정: `window.location.origin`이 유효하면 `origin + "/api"`를 사용, 아니면 기본 `http://localhost:8000/api`.
- 세일즈맵 링크: `SALESMAP_WORKSPACE_PATH` 상수로 workspace id를 설정.

## 2) 전역 state 구조(주요 필드)
- `activeMenuId`: 현재 메뉴 id (`org-view`, `rank-2025`, `rank-2025-people`, `mismatch-2025`, `industry-2025`).
- `size`, `rankSize`, `rankPeopleSize`, `mismatchSize`: 규모 필터.
- `rankPeopleOrgFilter`, `rankPeopleUpperFilter`: 텍스트 필터.
- `orgs`, `orgSearch`, `selectedOrg`, `selectedUpperOrg`, `selectedPerson`, `selectedDeal`.
- 데이터 보관: `people`, `deals`, `orgMemos`, `personMemos`, `dealMemos`, `wonSummary`, `wonGroupJson`, `filteredWonGroupJson`.
- 모달 상태: `modal`(메모), `jsonModal`, `webformModal`, `rankPeopleModal`(딜 리스트).
- 캐시: 별도 `cache` 객체(Map)로 관리(아래 참조).
- 디버그: `DEBUG_ORG_SELECT`/`setOrgSelectDebug`로 조직 선택 디버그 로그 제어.

## 3) cache 구조/정책
- Map 캐시: `orgLookup`, `orgMemos`, `peopleByOrg`, `deals`, `personMemos`, `dealMemos`, `wonSummary`, `wonGroupJsonByOrg`, `rank2025BySize`, `rank2025PeopleBySize`, `mismatch2025BySize`.
- 무효화 없음: 새 DB로 교체 시 브라우저 새로고침 필요.
- 캐시 적중 시 API 호출을 건너뛰고 즉시 렌더.

## 4) 핵심 사용자 플로우
1. 조직 목록 로드: `/api/orgs` 호출(규모/검색/limit=200/offset). People/Deal이 1건 이상 있는 조직만, 2025 Won desc 정렬. 결과 0건 + 검색어 없음 → 규모를 `전체`로 바꿔 재조회. 자동 선택 없음.
2. 조직 선택: 드롭다운 선택 시 `loadOrgDetail` → `/orgs/{id}/memos`, `/orgs/{id}/people`, `/orgs/{id}/won-summary` 병렬 호출 → 상태/표 갱신.
3. 상위 조직 선택: Won 요약 표 행 클릭 → `selectedUpperOrg` 설정 → People/Deal/메모 표를 상위 조직 필터로 렌더. Won 그룹 JSON도 필터(`filterWonGroupByUpper`).
4. People 선택: People 행 클릭 → Deals fetch(`/people/{id}/deals`) → Deal 메모 fetch(`/deals/{id}/memos`) → 관련 표/모달 갱신.
5. JSON 버튼: `/orgs/{id}/won-groups-json`을 캐시 후 전체/선택 상위 조직 JSON 모달/복사. 선택 없으면 버튼 비활성화 + 안내 문구.
6. 선택 초기화: 규모/검색/회사 선택 상태를 기본으로 리셋하고 목록 재조회. 상위 조직/People/Deal/메모/Won 요약/JSON 상태도 초기화한다. 자동 선택 없음.

## 5) 메뉴별 동작 요약
- **조직/People/Deal 뷰어(`org-view`)**: 조직 목록/메모/People/Deal/메모, 상위 조직 Won 요약, 상위 조직별 JSON, 웹폼 내역 모달(People 행 버튼), 딜/People 세일즈맵 링크.
- **2025년 체결액 순위(`rank-2025`)**: `/api/rank/2025-deals` 호출, 규모 필터, 과정포맷별 금액 목록 모달.
- **2025 대기업 딜·People(`rank-2025-people`)**: `/api/rank/2025-deals-people`, 규모/회사/상위 조직 필터, 딜 보기 모달.
- **고객사 불일치(`mismatch-2025`)**: `/api/rank/mismatched-deals`, 규모 필터, 딜 org vs People org 비교.
- **업종별 매출(`industry-2025`)**: `/api/rank/won-industry-summary`, 업종 구분(대)별 23/24/25 Won 합계/회사 수 표시.

## 6) UX 정책
- 토스트: 성공/정보/에러 메시지를 하단에 3.2초 노출.
- 모달: 메모/JSON/웹폼/딜 보기 모달. ESC, 닫기 버튼, 배경 클릭으로 닫힘.
- 버튼 비활성화: 데이터 없는 상태에서 JSON 보기/복사, 웹폼 내역(없으면 “없음”), 조직 미선택 시 People/Deal 표 비움, 상위 조직 미선택 시 관련 표/버튼 비활성화.
- 선택 표시: 선택된 행은 `active` 클래스, 상위 조직 라벨/브레드크럼에 선택 상태 반영.
