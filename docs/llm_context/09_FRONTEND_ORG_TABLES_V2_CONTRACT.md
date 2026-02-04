---
title: org_tables_v2 프런트 계약
last_synced: 2026-02-04
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - tests/test_pl_progress_2026.py
  - tests/test_perf_monthly_contracts.py
  - tests/test_perf_monthly_inquiries.py
  - tests/test_perf_monthly_inquiries_online_first_filter.py
  - tests/test_qc_r13_r17_hidden.py
absorbed_from:
  - org_tables_v2.md
  - json_logic.md
---

## Purpose
- 정적 프런트 `org_tables_v2.html`의 메뉴/상태/렌더/캐시/모달 계약을 코드 기준으로 명세한다.

## Behavioral Contract
- 사이드바: `MENU_SECTIONS` 순서로 사업부 퍼포먼스(2026 P&L → 2026 월별 체결액 → 2026 Daily Report(WIP)) → 운영(2026 Targetboard(출강), 2026 Targetboard(온라인), 2026 카운터파티 DRI, 딜체크 7개 메뉴) → 분석(StatePath 24→25, 2025 체결액 순위, 조직/People/Deal 뷰어, 숨김: 2025 대기업 딜·People/업종별 매출) → 검수(개인별 세일즈맵 검수, 고객사 불일치). 해시가 유효하지 않으면 `DEFAULT_MENU_ID="target-2026"`. 딜체크 메뉴는 단일 config(`DEALCHECK_MENU_DEFS`)에서 부모 2개(교육1/교육2)와 자식 5개(교육1: 1/2파트, 교육2: 1/2파트/온라인셀)를 정의하며, 자식 라벨에만 `↳ ` 접두어를 추가한다. 월별 체결액도 동일 패턴으로 부모 `biz-perf-monthly` 아래 하위 메뉴 2개(교육1/교육2)가 있으며 `team` 파라미터를 전달한다.
- 사업부 퍼포먼스 메뉴 확장: `biz-perf-monthly-edu2` 하위에 `biz-perf-monthly-edu2-inquiries`(라벨: “2026 문의 인입 현황”, kind=monthly-inquiries, suppressArrow=true)가 추가되며 parentId는 유지되지만 사이드바 라벨 앞 `↳`는 이 메뉴에만 표시하지 않는다(다른 하위 메뉴는 기존 `↳` 유지).
- API_BASE: origin이 있으면 `<origin>/api`, 아니면 `http://localhost:8000/api`.
- 데스크톱(>900px): `html{height:100%}`, `body{height:100vh; overflow:hidden}`으로 페이지 스크롤을 막고 `.layout{grid-template-rows:1fr; flex:1 1 auto; min-height:0; overflow:hidden; align-items:stretch}` 아래 사이드바/콘텐츠를 분리 스크롤한다. 사이드바는 `min-height:0; overflow:hidden`, 메뉴 리스트는 `overflow-y:auto`, 콘텐츠는 `overflow:auto`이며 `.content#contentScroll`에 스크롤이 쌓인다. 메뉴 클릭 시 `scrollRightContentToTop()`이 `.content`를 top=0으로 리셋한다.
- 모바일(<=900px): @media에서 body/레이아웃/사이드바/메뉴/콘텐츠 height·overflow를 auto/visible로 되돌려 단일 페이지 스크롤을 유지한다.
- 2026 P&L (`renderBizPerfPlProgress2026`):
  - `/performance/pl-progress-2026/summary` → 연간(T/E) 후 2601~2612 T/E 컬럼을 렌더. 현재 월 헤더/셀에 `is-current-month-group`/`is-current-month` 클래스 부여.
  - assumptions 바(공헌이익률 온라인/출강, 월 제작/마케팅/인건비) 입력 → `applyAssumptionsToPnlData`로 즉시 재계산. `pnlAssumpInfoBtn`은 meta.excluded·snapshot_version·가정을 모달로 표시, `pnlResetAssumptionsBtn`은 기본값으로 복구.
  - 월별 E 열(REV_TOTAL/REV_ONLINE/REV_OFFLINE)만 클릭 가능, `/performance/pl-progress-2026/deals` 결과를 recognizedAmount desc→amountUsed desc→dealName desc 정렬해 모달 테이블로 표시.
- 2026 월별 체결액 (`renderBizPerfMonthly`):
  - `/performance/monthly-amounts/summary` → YYMM 24개월, rows TOTAL→CONTRACT→CONFIRMED→HIGH, segment 11종. 값은 `formatEok1`로 억 1자리, dealCount=0이면 `<span class="mp-cell-btn is-zero">` 비활성. 하위 메뉴(교육1/교육2)는 `team=edu1|edu2`를 함께 전달한다.
  - 셀 클릭 시 `/performance/monthly-amounts/deals`, amount>0 우선→expectedAmount→dealName asc 정렬 후 모달 테이블(카테고리 포함 16열, colgroup 일부 고정) 표시. 팀별 메뉴는 동일한 team 파라미터를 사용한다.
- 2026 문의 인입 현황 (`renderBizPerfMonthlyInquiries`):
  - `/performance/monthly-inquiries/summary`를 한 번 불러오고, 화면에서는 **기업 규모 버튼 바(대기업/중견기업/중소기업/공공기관/대학교/기타/미기재, 기본=대기업)** 로 선택한 규모만 필터링해 렌더한다. 버튼은 `data-inq-size` + `is-active`/`aria-pressed`를 사용하고 `normalizeInqSizeGroupKey`로 백엔드 값의 변형을 흡수한다.
  - 테이블 sticky 컬럼은 2개(과정포맷, 카테고리)이며 월 헤더는 24개 고정(2025-01~2026-12). parent row는 (선택 규모, 과정포맷) 합산(level=1, rowKey=`<fmt>||__ALL__`)만 기본 노출되고, child row는 카테고리 상세(level=2, rowKey=`<fmt>||<cat>`; cat=온라인/생성형AI/DT/직무별교육/스킬/기타/미기재)가 `style=display:none`으로 뒤따라 렌더된다.
  - parent `<tr.inq-parent>` 클릭 시 동일 parentId(과정포맷)를 가진 `<tr.inq-child>`의 display를 토글하고 caret `▸/▾`를 바꾼다. 숫자 버튼 클릭은 이벤트 분리돼 모달 호출만 수행한다.
  - 자식 카테고리 셀 라벨은 `┗ ` 접두어를 붙이며, count=0은 `<span class="mp-cell-btn is-zero">`, 0 초과는 `<button class="mp-cell-btn" data-perf-kind="monthly-inquiries" data-segment="<선택규모>" data-row="<rowKey>" data-month="YYMM">`.
  - 딜 팝업은 월별 체결액 모달을 재사용하며 제목만 “월별 문의 인입”으로 바뀐다. 테이블에 `카테고리` 컬럼이 과정포맷 오른쪽에 추가되고, `normalizeDealCategoryText`로 공백/null을 “미기재”로 표기한다. colspan은 16, teamKey=edu2, kind="monthly-inquiries"가 전달된다.
- 카운터파티 DRI (`renderRankCounterpartyDriScreen`):
  - `/rank/2025-top100-counterparty-dri`를 호출해 규모별 **전체 리스트**를 캐싱하고 검색/DRI(O/X/all)/팀&파트 필터를 클라이언트에서 적용하며, 정렬은 고정(orgWon2025 desc → cpTotal2025 desc). Prev/Next 페이징 없이 전체를 한 번에 렌더하며, 행 클릭 시 `/rank/2025-counterparty-dri/detail`.
- 2026 Targetboard(출강/온라인): `/rank/2025-top100-counterparty-dri`를 한 번만 불러와 클라이언트에서 카드 KPI를 계산한다. 섹션은 전체 + 조직별 5개(기업교육 1팀 1/2파트, 2팀 1/2파트, 2팀 온라인셀) 스택으로 렌더하며, 각 섹션마다 티어별 8카드(S0/P0/P1/P2/P3/P4/P5/N)를 출력한다. 출강 모드는 override row만 포함, 온라인 모드는 모든 row 포함. 카드 메트릭은 소수점 1자리 억 단위(won/target), 서브라인은 규모별 target 합계를 소수점 1자리로 표기한다. 카드 클릭/Enter/Space 시 모달이 뜨며 컬럼은 티어/기업명/카운터파티/팀&파트/담당자/26 체결/26 타겟이고, 타이틀은 “섹션명 · 카드명”으로 표시된다(담당자는 DRI 화면과 동일 포맷: 1명→이름, 2명 이상→“첫번째 외 N명”, 없으면 “미입력”).
- 2026 온라인 리텐션: `/ops/2026-online-retention`을 호출해 상태=Won, 생성일≥2024-01-01, 온라인 과정포맷 3종, 금액/수강시작/수강종료/코스ID가 모두 있는 딜만 받아 2024-10~2027-12 수강종료월별 섹션으로 표를 렌더한다. 컬럼은 기업명/상위조직/팀/담당자/생성일/딜명/과정포맷/파트/데이원 + 상태/금액/(온라인)입과 주기/(온라인)최초 입과 여부/수강시작일/수강종료일/메모 버튼(메모 확인/메모 없음) 순으로 고정된다. 파트는 owners를 resolveOwnerTeamPart로 해석해 1/2/온라인셀 조합 문자열을 표시한다.
- 딜체크/QC:
  - `renderDealCheckScreen(teamKey, options)` 한 곳에서 7개 딜체크 메뉴를 공통 렌더하며, `/deal-check/edu1`·`/deal-check/edu2`(또는 `/deal-check?team=`) 결과를 orgWon2025Total desc→createdAt asc→dealId asc로 렌더, memoCount=0이면 “메모 없음” 비활성 버튼. 부모 메뉴는 필터 없이 팀 전체를, 자식 메뉴는 `partFilter`(1/2파트/온라인셀)를 받아 owners→`getDealCheckPartLookup` 룩업 기반으로 클라이언트 필터를 적용한다. 섹션은 공통 6분할(리텐션 S0~P2 비온라인→온라인→신규 온라인→리텐션 P3~P5 온라인→비온라인→신규 비온라인) 순서를 유지한다.
  - 딜체크 테이블 컬럼 순서는 (티어, 선택적으로) 기업명/상위조직/팀/담당자/생성 날짜/딜 이름/과정포맷/**기획**/파트/데이원/가능성/수주 예정일/예상/메모이며, `기획` 칼럼은 항상 “링크” 텍스트를 표시하되 `planningSheetLink`가 http(s)로 시작할 때만 새 탭 링크로 감싼다.
  - `renderDealQcR1R15Screen`은 `/qc/deal-errors/summary` 카드(팀별 총이슈 desc) + `/qc/deal-errors/person` 상세 모달을 제공한다. 프런트는 표시 가능 규칙 Set을 `R1~R16`로 정의하지만 **UI는 R1~R15만 노출**하며 issueCodes에서 이 집합에 없는 코드는 렌더 단계에서 필터한다. R13 가이드는 “대기업/중견 · Won 또는 SQL · 담당자 메타 결측”으로 표기한다. 숨김 규칙(R17)은 summary totalIssues/byRule, 모달 issueCodes 모두에서 제외된다.
- 조직/People/Deal 뷰어:
  - `getSizes`→`/orgs`로 조직 목록 로드, 선택 시 `/orgs/{id}/people`→사람 선택→`/people/{id}/deals`/`/people/{id}/memos`/`/deals/{id}/memos`.
  - 상위 조직 JSON 카드: `/orgs/{id}/won-groups-json` 캐시 → 선택 upper_org가 없으면 JSON 버튼 비활성+안내, 선택 시 전체/선택 JSON 모달, compact 버튼은 `/won-groups-json-compact`.
  - 메모 표시: `htmlBody`가 있으면 sanitizer를 거쳐 서식 유지 렌더(DIV/테이블/thead/tbody/tr/th/td/링크 허용, href 검증 + `_blank`/`noopener` 강제), 없으면 text를 `white-space: pre-wrap`으로 표시한다. 딜체크 “메모 확인” 모달 포함 모든 모달이 이 규칙을 사용한다.
- StatePath 24→25: 서버 호출은 `segment/sort/limit`만 전달하며, 필터는 모두 클라이언트 드로어(규모 라디오, 2024 티어 프리셋/체크박스, Quick Filters, 패턴 필터 전이/셀/rail)에서 즉시 적용된다. Snapshot/Pattern Explorer/테이블/브레드크럼이 공유 상태를 사용하고 “전체 해제” 버튼이 클라이언트 필터를 리셋한다. Glossary/Legend 모달과 Core JSON 복사 버튼(StatePath 상세)이 포함돼 필터 기준과 복사 스키마를 안내한다.
- 2026 Daily Report(WIP, Counterparty Risk): 날짜 선택+새로고침 버튼, tier/risk 멀티셀렉트, pipeline_zero 토글, 검색, 리스크 칩을 제공한다. `/report/counterparty-risk` 응답의 summary.tier_groups/summary.counts/data_quality와 counterparties[*](`target_2026/coverage_2026/expected_2026/gap/coverage_ratio/pipeline_zero/evidence_bullets/recommended_actions`)를 표시하며, 섹션별 details 토글이 evidence/추천 액션을 노출한다. DB 버전 배지를 표시하고 필터 상태는 메모리 캐시(Map)로 유지된다.
- 2025 체결액 순위: 규모 셀렉터 + 등급 가이드/배수 설정 모달을 갖추고, `/rank/2025-deals`만 호출해 받은 데이터를 프런트에서 `computeTargets`로 재계산해 26 타겟/온라인/비온라인 컬럼을 렌더한다(삼성 S0는 50억 고정). `/rank/2025/summary-by-size`는 UI에서 사용하지 않는다.
### (흡수) UI/렌더 세부 규칙
- 카운터파티 DRI 화면은 `/rank/2025-top100-counterparty-dri?size=...`로 규모별 **전체 조직**을 한 번에 불러와 캐시에 보관하고, 검색/DRI(O/X/all)/팀&파트 필터를 모두 클라이언트에서 적용한다. Prev/Next 없이 한 화면에서 필터링하며 기본 정렬은 orgWon2025 desc→cpTotal2025 desc다. target26 컬럼은 override 시 강조한다.
- 상위 조직 JSON 카드는 선택이 없으면 버튼이 비활성화되고 안내 문구를 표시한다. 전체 JSON은 원본 그대로, 선택 JSON은 `filterWonGroupByUpper`로 groups만 upper_org 일치 항목을 필터링하며 organization 블록은 그대로 유지한다. compact 버튼은 `/won-groups-json-compact` 응답을 사용해 `schema_version=won-groups-json/compact-v1`과 `htmlBody` 제거 여부를 확인한다.
- 2026 P&L은 헤더/셀에 `is-current-month-group`/`is-current-month` 클래스로 현재 월을 강조하고 월별 E 열만 클릭 가능하다. assumptions 바는 변경 시 `is-dirty` 클래스로 표시되며 `pnlAssumpInfoBtn`이 제외 건수·스냅샷 버전·가정을 모달로 보여준다.
- 월별 체결액/문의 인입 공용 딜 모달은 amount>0 우선→expectedAmount→dealName asc로 정렬된 테이블을 사용하며, `카테고리` 컬럼이 과정포맷 오른쪽에 추가돼 총 16열이다. dealCount 0 셀은 `<span class=\"mp-cell-btn is-zero\">`로 비활성 처리된다. 모달은 `.modal.deals-modal-wide` flex 레이아웃을 사용해 헤더를 고정(`.deals-modal-header`)하고 본문 `.body`를 `flex:1` + `min-height:0`로 설정, 실제 스크롤은 `.deals-modal-scroll`에서만 발생한다(폭: min(96vw,1400px), 높이: min(90vh,900px)).
- 딜체크 7개 메뉴는 모두 `DEALCHECK_MENU_DEFS`에서 파생된 동일 renderer를 사용하고, memoCount=0일 때 “메모 없음” 비활성 버튼을 보여준다. 섹션은 리텐션 S0~P2 비온라인→온라인→신규 온라인→리텐션 P3~P5 온라인→비온라인→신규 비온라인 순서로 고정된다.

## Invariants (Must Not Break)
- 메뉴 섹션/라벨/순서/ID는 `MENU_SECTIONS` 정의와 일치해야 하며, 잘못된 hash 시 org-view로 이동해야 한다.
- P&L 테이블: 연간(T/E) → 월별(T/E) 순, 현재 월 하이라이트, 월별 E만 클릭 가능, 숫자 우측 정렬(tabular-nums), 0은 버튼 대신 span.
- 월별 체결액: rows 4개·YYMM 24개 전부 출력, dealCount=0 셀은 비활성 span, 금액은 `formatEok1`(원→억) 사용.
- 문의 인입 현황: SIZE_ORDER 7개 버튼 중 선택한 규모만 렌더하며 기본 선택은 "대기업". sticky 컬럼은 과정포맷/카테고리 2개, child 행은 기본 숨김, parent 클릭 시 caret과 함께 토글되어야 한다. 버튼 셀에는 `data-perf-kind="monthly-inquiries"`와 segment=rowKey=month dataset이 모두 설정돼야 한다.
- 모달 공유 DOM(`#rankPeopleModal*`, `#dealQcModal`, JSON/StatePath 모달)을 재사용하며 ESC/백드롭/X로 닫혀야 한다. 딜 모달은 `.deals-modal-wide` flex 스크롤 구조(헤더 고정, `.deals-modal-scroll`에서만 overflow)와 max-height `min(90vh,900px)`을 유지해야 마지막 행이 잘리지 않는다.
- 캐시: 공통 fetchJson은 캐시를 두지 않으며 화면별로 Map 캐시(state/cache 객체)를 개별 보관한다. DB 교체/포트 변경 시 새로고침 전에는 각 화면 캐시가 무효화되지 않는다. 딜체크 7개 메뉴는 모두 `DEALCHECK_MENU_DEFS`에서 파생된 동일 renderer를 사용해야 하며, 메뉴 추가 시 config 1곳만 수정하면 사이드바/renderer가 함께 반영돼야 한다.
- StatePath 필터 드로어의 토글/싱글 선택(전이/셀/rail/seed/회사 방향/위험 등)은 서버 재호출 없이 클라이언트 필터만 변경해야 하며, Snapshot/Pattern/테이블이 즉시 동기화된다.
- Counterparty Risk 화면은 tier/risk/pipeline_zero/search 필터를 모두 프런트에서 적용하고, summary(티어별 target/coverage/gap/coverage%)와 evidence/추천 액션 토글을 표시해야 한다.
- DRI 테이블은 target26(오프라인/온라인) 컬럼과 override 강조 클래스를 렌더해야 하며, 팀&파트 옵션은 owners2025 기반으로 재계산된다.
- 2025 체결액 순위 테이블에는 26년 타겟/온라인/비온라인 컬럼과 등급 배수/가이드 모달 버튼이 포함돼야 한다. Target Board 카드 그룹은 DRI 원본을 기반으로 티어별 합계를 보여야 한다.
- StatePath 도움말(Glossary/Legend)과 Core JSON 복사 버튼은 렌더/작동해야 하며, 서버 재호출 없이 클라이언트 상태만 업데이트해야 한다.

## Coupling Map
- 프런트: `org_tables_v2.html` 렌더러/상수(`MENU_SECTIONS`, `DEFAULT_MENU_ID`, `PART_STRUCTURE`, `COUNTERPARTY_ONLINE_FORMATS`, inquiries size bar/accordion, `normalizeInqSizeGroupKey`, `normalizeDealCategoryText` 등).
- API: `dashboard/server/org_tables_api.py`(`/performance/*`, `/rank/*`, `/statepath/*`, `/deal-check*`, `/qc/*`, `/orgs/*`) ↔ `dashboard/server/database.py`/`statepath_engine.py`.
- 테스트: `tests/test_pl_progress_2026.py`, `tests/test_perf_monthly_contracts.py`가 P&L/월별 계약을, `tests/test_perf_monthly_inquiries.py`/`tests/test_perf_monthly_inquiries_online_first_filter.py`가 문의 인입 요약/필터를, `tests/test_api_counterparty_dri.py`가 DRI 집계를 검증한다.

## Edge Cases & Failure Modes
 - fetch 실패 시 각 섹션 루트에 muted 오류 문구, 토스트 표시. 모달은 로딩 텍스트로 초기화 후 실패 시 오류 문구만 남는다.
 - 캐시로 인해 DB 교체 후 새로고침 전까지 이전 데이터가 남는다. 문의 인입 현황도 summary를 1회 로드 후 규모 필터만 클라이언트에서 적용하므로 DB 교체 시 새로고침이 필요하다.
 - hash가 숨김 메뉴 id(`rank-2025-people`, `industry-2025`)일 때도 렌더는 되지만 사이드바에 표시되지 않는다.
 - 선택 초기화 시 People/Deal/메모/JSON 상태가 모두 리셋되어야 하며, 누락 시 이전 데이터가 잔류할 수 있다.
 - Counterparty Risk는 evidence/recommendations가 없을 때 placeholder를 보여주며, DB 교체 후 새로고침하지 않으면 이전 캐시를 계속 사용한다.
 - StatePath는 segment만 서버에 전달하고 나머지 필터는 프런트 상태에만 존재하므로, DB 교체 시 새로고침을 하지 않으면 구 데이터를 계속 필터링할 수 있다.

## Verification
- 사이드바 라벨/순서가 계약대로인지, 잘못된 hash 시 조직 뷰어가 열리는지 확인한다.
- 데스크톱에서 body에 스크롤바가 없고 `.sidebar`/`.content` 각각 세로 스크롤바가 표시되는지, 메뉴 클릭 시 `.content`가 항상 top=0으로 리셋되는지 확인한다.
- `/performance/pl-progress-2026/summary` 응답으로 연간→월별 T/E 헤더와 현재 월 하이라이트가 표시되고, 월별 E 셀 클릭 시 `/performance/pl-progress-2026/deals` 모달이 recognizedAmount desc→amountUsed desc→dealName desc 정렬인지 확인한다.
 - `/performance/monthly-amounts/summary`가 24개월·4개 row를 모두 포함하고 0 셀이 비활성화되며, 모달 정렬이 amount>0→expectedAmount→dealName asc인지 확인한다.
 - `/performance/monthly-inquiries/summary`가 7개 size·13 과정포맷 rollup과 카테고리(온라인/생성형AI/DT/직무별교육/스킬/기타/미기재) 상세를 모두 포함하는지, size 버튼 전환 시 테이블이 해당 규모 데이터로 재렌더되는지 확인한다.
 - 문의 인입 테이블 parent 클릭 시 child 행이 접기/펼치기 되고, 숫자 버튼 클릭 시 `/performance/monthly-inquiries/deals` 모달이 열리며 카테고리 컬럼이 표시되는지(공백→미기재) 확인한다.
 - 월별 체결액/문의 인입 딜 모달을 열어 스크롤을 끝까지 내려도 마지막 행이 잘리지 않고 완전히 보이는지 확인한다(헤더 2줄 상황 포함).
- 사이드바에서 `2026 문의 인입 현황` 라벨만 `↳` 없이 노출되고 다른 하위 메뉴는 기존 `↳`를 유지하는지 확인한다.
- `/rank/2025-top100-counterparty-dri` 호출 후 검색/DRI/팀&파트 필터가 즉시 반영되고 행 클릭 시 `/rank/2025-counterparty-dri/detail` 모달이 열리는지 확인한다.
- 딜체크 메뉴 7개가 모두 표시되고, `/deal-check?team=edu1|edu2` 결과가 orgWon2025Total desc→createdAt asc→dealId asc 정렬인지 확인한다. 자식 메뉴(파트/온라인셀)는 owners 기반 partFilter가 적용돼 카운트/목록이 달라지는지 검증한다.
- 상위 조직 JSON 카드에서 선택 없을 때 버튼 비활성+안내, 선택 후 전체/선택 JSON/compact 모달이 올바른 데이터를 표시하는지 확인한다.
 - StatePath: 필터 드로어(규모/티어/Quick Filters/패턴)가 Snapshot/Pattern/테이블에 즉시 반영되고 “전체 해제”가 클라이언트 필터를 모두 리셋하는지 확인한다.
 - Counterparty Risk Daily: tier/risk/pipeline_zero/search 필터가 리스트에 적용되고 summary/DQ 배지와 evidence/추천 액션 토글이 표시되는지, DB 버전 배지가 나타나는지 확인한다.
 - 랭킹: 등급 가이드/배수 모달이 열리고 26 타겟/온라인/비온라인 컬럼이 렌더되는지, Target Board가 DRI 기반 KPI 카드를 그리는지 확인한다.

## Refactor-Planning Notes (Facts Only)
 - `org_tables_v2.html` 단일 파일에 메뉴/렌더러/모달/CSS가 모두 포함되어 구조 변경 시 전 화면에 영향이 퍼진다.
 - 모달 DOM과 fetch 캐시를 여러 화면이 공유해 상태 충돌 위험이 있으며, 정리되지 않은 상태가 다른 화면에 잔류할 수 있다. 딜 모달 컬럼 수(16)와 colspan이 하드코딩돼 있어 구조 변경 시 동시 수정이 필요하다.
 - 온라인 판정/타겟 상수 등이 백엔드와 중복돼 있어 규칙 변경 시 JS/파이썬 양쪽을 동시에 수정해야 한다.
 - Counterparty Risk/StatePath/Target Board 등 신규 화면은 클라이언트 필터/계산 의존도가 높아, 서버 파라미터를 추가할 때 프런트 상태 모델을 함께 조정해야 한다.
