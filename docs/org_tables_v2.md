---
title: org_tables_v2 동작 정리 (FastAPI 기반)
last_synced: 2026-01-12
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - dashboard/server/json_compact.py
  - tests/test_pl_progress_2026.py
  - tests/test_perf_monthly_contracts.py
  - tests/test_api_counterparty_dri.py
---

## Purpose
- 정적 프런트 `org_tables_v2.html`와 FastAPI `/api` 백엔드가 제공하는 대시보드(사업부 퍼포먼스/랭킹/StatePath/딜체크·QC/조직 뷰어)의 현재 계약을 코드 기준으로 기록한다.

## Behavioral Contract
- **사이드바·라우팅**: `MENU_SECTIONS` 순서대로 사업부 퍼포먼스(2026 P&L, 2026 월별 체결액, 2026 Daily Report(WIP)) → 운영(2026 Target Board, 2026 카운터파티 DRI, 딜체크 7개 메뉴) → 분석(StatePath 24→25, 2025 체결액 순위, 조직/People/Deal 뷰어, 숨김: 2025 대기업 딜·People/업종별 매출) → 검수(개인별 세일즈맵 검수, 고객사 불일치). URL hash가 유효하지 않으면 `DEFAULT_MENU_ID="org-view"`로 이동한다. 딜체크 메뉴는 단일 config(`DEALCHECK_MENU_DEFS`)에서 부모 2개(교육1/교육2)와 자식 5개(교육1: 1/2파트, 교육2: 1/2파트/온라인셀)를 정의하며, 라벨 앞에 `↳ ` 접두어만 붙여 서브메뉴를 표시한다(여백/들여쓰기 없음).
- **2026 P&L 진행율매출** (`renderBizPerfPlProgress2026`):
  - `/performance/pl-progress-2026/summary` 호출 후 Target(T)/Expected(E) 열을 `연간(T/E) → 2601(T/E) … 2612(T/E)` 순으로 렌더한다. 현재 월은 헤더에 `is-current-month-group`/셀 `is-current-month` 클래스로 하이라이트된다.
  - Assumptions 바는 공헌이익률(온라인/출강)·월 제작비/마케팅비/인건비를 입력받아 `applyAssumptionsToPnlData`로 재계산한다. `pnlAssumpInfoBtn` 클릭 시 제외 건수·스냅샷 버전·가정 요약을 모달로 표시하며 `pnlResetAssumptionsBtn`은 `DEFAULT_PNL_ASSUMPTIONS`로 복구한다.
  - 월별 E 열의 REV_TOTAL/REV_ONLINE/REV_OFFLINE만 클릭 가능하며 `/performance/pl-progress-2026/deals?year=2026&month=YYMM&rail=TOTAL|ONLINE|OFFLINE&variant=E` 결과를 recognizedAmount desc→amountUsed desc→dealName desc 정렬로 모달에 표기한다.
- **2026 월별 체결액** (`renderBizPerfMonthly`):
  - `/performance/monthly-amounts/summary`를 호출해 YYMM 24개월 고정, row `TOTAL→CONTRACT→CONFIRMED→HIGH`를 세그먼트별 카드로 렌더한다. 값은 원 단위를 `formatEok1`로 1e8 나눠 표시하며 dealCount가 0이면 `<span class="is-zero">`로 비활성화된다.
  - 셀 클릭 시 `/performance/monthly-amounts/deals`로 드릴다운하고, amount>0 우선→expectedAmount→dealName asc로 정렬해 모달 테이블(15열, colgroup 고정 폭)로 보여준다.
- **카운터파티 DRI** (`renderRankCounterpartyDriScreen`):
  - `/rank/2025-top100-counterparty-dri?size=...`로 규모별 **전체 조직**을 한 번에 불러와 캐시에 보관하고, 검색/DRI(O/X/all)/팀&파트 필터를 클라이언트에서 적용한다(정렬은 고정: orgWon2025 desc → cpTotal2025 desc). Prev/Next 페이징 없이 전체 리스트를 한 화면에서 필터링하며, target26(오프라인/온라인) 컬럼을 표시하고 override일 때 강조한다.
  - 행 클릭 시 `/rank/2025-counterparty-dri/detail?orgId=...&upperOrg=...`로 모달을 열어 딜 리스트를 표시한다.
- **2026 Target Board** (`renderTarget2026Screen`):
  - `/rank/2025-top100-counterparty-dri/targets-summary` + 규모별 DRI rows를 불러와 티어 그룹별 26 출강 체결/타겟 합계를 카드로 렌더한다. DRI 데이터가 없으면 “DRI 데이터 없음”을 표시한다.
- **딜체크·QC**:
  - `renderDealCheckScreen(teamKey, options)` 한 곳에서 7개 딜체크 메뉴를 공통 렌더하며, `/deal-check?team=edu1|edu2` 결과를 orgWon2025Total desc→createdAt asc→dealId asc로 테이블 렌더한다. memoCount=0이면 “메모 없음” 비활성 버튼을 보여준다. 부모 메뉴는 필터 없이 팀 전체를, 자식 메뉴는 `partFilter`(1/2파트/온라인셀)를 받아 owners→`getDealCheckPartLookup` 룩업 기반으로 클라이언트 필터를 적용한다. 화면 섹션은 공통 6분할(리텐션 S0~P2 비온라인→온라인→신규 온라인→리텐션 P3~P5 온라인→비온라인→신규 비온라인) 순서를 사용한다.
  - `renderDealQcR1R15Screen`은 `/qc/deal-errors/summary?team=edu1|edu2|public` 카드 3개(담당자/총이슈 desc)와 `/qc/deal-errors/person` 상세 모달(R1~R15 섹션만 노출)을 제공한다.
- **조직/People/Deal 뷰어**:
  - `getSizes`→`/orgs`로 조직 리스트를 불러오고, 회사 선택 시 `/orgs/{id}/people`→사람 선택→`/people/{id}/deals`/`/people/{id}/memos`/`/deals/{id}/memos`를 순차 호출한다.
- 상위 조직 JSON 카드에서 `/orgs/{id}/won-groups-json`을 캐싱하고 `filterWonGroupByUpper`로 그룹을 필터링한다. 선택 없으면 JSON 버튼 비활성 + 안내 문구 노출, 선택 시 전체/선택 JSON 모달을 별도로 제공하며 compact 버튼은 `/won-groups-json-compact`를 사용한다.
- 메모 표시 우선순위: `htmlBody`가 있으면 프런트에서 안전하게 Sanitized HTML로 렌더하고, 없으면 `text`를 `white-space: pre-wrap`으로 표시한다. 딜체크 “메모 확인” 모달 포함 모든 모달이 동일 규칙을 따른다.
- compact JSON 버튼(`/won-groups-json-compact`)은 HTML을 포함하지 않는 텍스트 중심 JSON이어야 하므로 `htmlBody`가 제거됐는지 확인한다.

## 수동 QA 체크리스트 (메모 관련)
- 딜체크 메모 모달: h2/h3가 과도하게 크지 않고 제목처럼 보이는지, ul/ol 중첩이 깨지지 않는지 확인한다.
- 메모 본문 링크가 새 탭으로 열리고 `rel="noopener noreferrer"`가 적용됐는지 DevTools로 확인한다.
- htmlBody가 없는 메모는 기존처럼 줄바꿈이 유지된 텍스트로 보이는지 확인한다.
- 간소화 JSON 보기/복사 결과에 HTML 태그나 `htmlBody` 키가 섞이지 않는지 확인한다.
- **기타 분석 뷰**: StatePath 24→25는 `/statepath/portfolio-2425` 결과를 segment/sort/limit만 서버에서 가져온 뒤 필터 드로어(규모 라디오, 2024 티어 프리셋/체크박스, Quick Filters, 패턴 필터 전이/셀/rail)를 전부 클라이언트 상태로 적용해 Snapshot/Pattern Explorer/테이블을 갱신하며 “전체 해제”가 필터를 리셋한다. `renderRank2025Screen`은 `/rank/2025/summary-by-size`와 `/rank/2025-deals`를 사용해 등급 가이드/배수 모달과 26 타겟(온라인/비온라인) 컬럼이 포함된 랭킹 표를 렌더한다. `renderCounterpartyRiskDaily`는 날짜 선택+필터(tier/risk/pipeline_zero/search)와 함께 `/report/counterparty-risk` 캐시 결과의 summary/counts/data_quality 및 counterparties 리스트(coverage/gap/target/expected/evidence/recommendations)를 표시한다.

## Invariants (Must Not Break)
- 메뉴 라벨·순서·섹션(`perf`→`ops`→`analysis`→`qa`)과 각 item id는 `MENU_SECTIONS` 정의와 일치해야 하며, 해시 미인식 시 `org-view`로 이동해야 한다. 딜체크 7개 메뉴는 모두 `DEALCHECK_MENU_DEFS`에서만 정의·파생되어야 하며, 별도 renderer 함수가 생기면 안 된다.
- P&L 테이블은 `연간(T/E) → 월별(T/E)` 순서와 year/month 헤더 병합 구조를 유지하고, 월별 E 셀만 클릭 가능하다. current YYMM은 헤더/셀 클래스(`is-current-month-group`/`is-current-month`)로 강조된다.
- Assumptions 입력 필드(공헌이익률 2개, 월 비용 3개)는 `pnl-assump` DOM 클래스와 `pnlResetAssumptionsBtn`/`pnlAssumpInfoBtn` 동작을 갖춰야 하며, dirty 상태(`is-dirty`)는 기본값 대비 변경 여부를 반영해야 한다.
- 월별 체결액 카드는 row 순서 4개·월 24개를 모두 출력하고, dealCount=0 셀은 `<span class="mp-cell-btn is-zero">`로 비활성 처리해야 한다. 금액 표시에는 `formatEok1`(원→억 변환)이 사용된다.
- 카운터파티 DRI 테이블은 기본 정렬 orgWon2025 desc→cpTotal2025 desc를 유지하며, 필터 적용 후 teamPart 옵션은 실제 owners2025 파생값으로만 채워야 한다. target26 컬럼은 override 여부에 따라 강조한다. detail 모달은 `/rank/2025-counterparty-dri/detail` 호출 후 열린다.
- Target Board 카드는 DRI rows 기반 티어 그룹 합계를 사용하며, DRI 데이터가 없으면 안내 문구를 보여야 한다.
- 딜체크 테이블은 memoCount 0일 때 버튼을 비활성화하고 orgWon2025Total desc→createdAt asc→dealId asc 정렬을 유지해야 한다. 6개 섹션 순서(리텐션 S0~P2 비온라인→온라인→신규 온라인→리텐션 P3~P5 온라인→비온라인→신규 비온라인)와 partFilter(owners 기반 룩업) 적용 여부는 메뉴별로 달라지지만 렌더 함수는 동일해야 한다. QC 상세 모달은 위배 룰이 없는 섹션을 숨기고 colgroup 폭을 고정해야 한다.
- 캐시: 공통 fetchJson은 캐시를 두지 않으며, 화면별로 Map 캐시(state/cache 객체)를 개별 보관한다. DB 교체 후 새로고침을 하지 않으면 각 화면 캐시에 이전 데이터가 남는다.
- StatePath 필터 드로어는 서버 재호출 없이 클라이언트 상태만 변경해야 하며 Snapshot/Pattern/테이블이 즉시 동기화돼야 한다.
- Counterparty Risk 화면은 tier/risk/pipeline_zero/search 필터를 프런트에서 적용하고 summary/counts/data_quality/meta.db_version을 표시해야 한다.

## Coupling Map
- 프런트: `org_tables_v2.html`의 렌더러(`renderBizPerfPlProgress2026`, `renderBizPerfMonthly`, `renderRankCounterpartyDriScreen`, `renderDealCheckScreen`, `renderStatePathMenu`, `renderOrgScreen` 등)와 공통 모달(`rankPeopleModal`, JSON/StatePath 모달, QC 모달)이 동일 DOM을 공유한다.
- API: `dashboard/server/org_tables_api.py`가 `/performance/*`, `/rank/*`, `/statepath/*`, `/deal-check*`, `/qc/*`, `/orgs/*`를 제공한다.
- 로직/DB: `dashboard/server/database.py`의 요약/드릴다운 집계(P&L, 월별 체결액, DRI, deal-check, Won JSON)와 `statepath_engine.py`, `json_compact.py`가 화면 데이터 원천이다.
- 테스트: `tests/test_pl_progress_2026.py`, `tests/test_perf_monthly_contracts.py`, `tests/test_api_counterparty_dri.py`가 집계/정렬/필터 계약을 보증한다.

## Edge Cases & Failure Modes
- fetch 실패 시 각 섹션 루트에 muted 오류 메시지를 표시하고 토스트를 띄운다. 모달 내부도 오류 문구만 표기하며 이전 데이터는 지운다.
- API 캐시가 브라우저 메모리에 남아 있어 DB를 교체해도 새로고침 전까지 이전 결과가 노출된다.
- 해시가 숨김 메뉴 id(`rank-2025-people`, `industry-2025`)일 때도 렌더는 수행되지만 사이드바 표시가 숨김 상태로 유지된다.
- 조직/People 선택이 없을 때 JSON 버튼이 비활성화되고 안내 문구가 노출된다. 드롭다운 초기화 시 이전 People/Deal/메모 상태를 전부 비운다.
- 모달은 ESC/백드롭/X 버튼으로 닫히며, 모달 DOM을 공유하므로 한 화면에서 에러가 나면 다른 화면도 동일 모달 상태의 영향을 받는다.
- StatePath 필터는 클라이언트 상태만 갱신하므로 DB를 교체했는데 새로고침을 안 하면 이전 데이터 기반으로 필터링될 수 있다.
- Counterparty Risk는 evidence/recommendations가 없을 때 placeholder를 노출하며, DB 교체 후 새로고침 전에는 이전 캐시를 계속 사용한다.

## Verification
- 사이드바에 사업부 퍼포먼스→운영→분석→검수 순으로 라벨이 노출되고, 잘못된 hash 진입 시 조직 뷰어가 기본으로 열리는지 확인한다.
- `/performance/pl-progress-2026/summary` 응답으로 연간(T/E)→월별(T/E) 헤더, 현재 월 하이라이트, 월별 E 셀 클릭 시 `/performance/pl-progress-2026/deals` 모달이 recognizedAmount desc→amountUsed desc→dealName desc 정렬로 뜨는지 확인한다.
- `/performance/monthly-amounts/summary`가 24개월·4개 row를 모두 포함하고 값 0인 셀은 버튼이 비활성화되는지, 셀 클릭 시 deals 모달이 amount>0→expectedAmount 순으로 정렬되는지 확인한다.
- `/rank/2025-top100-counterparty-dri` 호출 후 검색/DRI/팀&파트 필터가 즉시 테이블에 반영되고 target26 컬럼이 override 강조를 표시하는지, 행 클릭 시 `/rank/2025-counterparty-dri/detail` 모달이 열리는지 확인한다.
- 딜체크 메뉴 7개가 모두 표시되고, `/deal-check?team=edu1|edu2` 응답을 기반으로 orgWon2025Total desc→createdAt asc→dealId asc 정렬이 유지되며 memoCount 0일 때 버튼이 비활성화되는지 확인한다. 자식 메뉴(파트/온라인셀)는 owners 기반 partFilter가 적용돼 목록/카운트가 달라지는지 확인한다.
- `/orgs/{id}/won-groups-json` 호출 후 상위 조직을 선택해야만 “선택 상위 조직 JSON” 버튼이 활성화되고 compact 버튼이 `/won-groups-json-compact`를 사용해 schema_version을 포함하는지 확인한다.
- StatePath: 필터 드로어(규모/티어/Quick Filters/패턴)가 Snapshot/Pattern/테이블에 즉시 반영되고 “전체 해제”가 클라이언트 필터를 모두 리셋하는지 확인한다.
- Counterparty Risk Daily: tier/risk/pipeline_zero/search 필터가 리스트에 적용되고 summary/counts/data_quality/meta.db_version과 evidence/추천 액션 토글이 표시되는지, DB 버전 배지가 나타나는지 확인한다.
- Target Board: DRI 데이터가 있을 때 카드에 26 출강 체결/타겟 합계가 렌더되고, 데이터가 없으면 안내 문구가 노출되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- `org_tables_v2.html` 단일 파일에 모든 렌더러·모달·스타일이 집중돼 있어 DOM 구조 변경이 전체 화면에 파급될 수 있다.
- fetch 캐시(Map)와 모달 DOM을 여러 화면이 공유하므로 API 경로/모달 구조 변경 시 캐시 키·이벤트 바인딩 동기화가 필요하다.
- P&L/월별 체결액/DRI/딜체크 등 여러 화면이 동일 전역 상태(`state.rankPeopleModal`, `state.rankCounterpartyDri`)를 공유해 동시 렌더 시 상태 충돌 위험이 있다.
