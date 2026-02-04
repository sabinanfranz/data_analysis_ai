---
title: org_tables_v2 프런트 계약
last_synced: 2026-02-04
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - tests/org_tables_v2_frontend.test.js
  - tests/test_pl_progress_2026.py
  - tests/test_perf_monthly_contracts.py
  - tests/test_perf_monthly_inquiries.py
  - tests/test_perf_monthly_inquiries_online_first_filter.py
  - tests/test_qc_r13_r17_hidden.py
---

## Purpose
- 정적 단일 파일 대시보드 `org_tables_v2.html`의 메뉴/상태/렌더/모달/캐시 계약을 코드·테스트 기준으로 명세한다.

## Behavioral Contract
### 글로벌 레이아웃/상태
- 메뉴/섹션: `MENU_SECTIONS` 정의 순서 그대로 렌더. 기본 hash 없을 때 `DEFAULT_MENU_ID="target-2026"` 선택. 숨김 메뉴(`rank-2025-people`, `industry-2025`)는 사이드바 미노출이지만 hash로 열 수 있다.
- API_BASE: `window.location.origin` 존재 시 `<origin>/api`, 그 외 `http://localhost:8000/api`.
- 데스크톱(>900px): body height 100vh, 전체 스크롤 금지. `.layout` 그리드(240px/1fr), `.sidebar`와 `.content` 각각 세로 스크롤 분리; 메뉴 클릭 시 `scrollRightContentToTop()`으로 `.content`를 top=0 리셋. 모바일(<=900px): overflow 복원, 단일 스크롤.
- 캐시: fetchJson 자체는 캐시 없음. 화면별 state/cache(Map)를 보관; 새로고침 전에는 DB 교체가 반영되지 않는다. org 선택 JSON/people/deal/memo 캐시, DRI/Targetboard/StatePath/Performance/Inquiry 등은 각 화면별 Map에 저장.

### 메뉴/렌더러 요약
- 사업부 퍼포먼스 섹션: P&L(2026) → 월별 체결액(전체/1팀/2팀) → 문의 인입(2팀) → 체결률 2026 → Daily Report(출강/온라인).
- 운영 섹션: Targetboard 2026(출강/온라인) → Counterparty DRI 2026 → 온라인 리텐션 2026 → 딜체크 7개(1팀/2팀 + 파트/온라인셀).
- 분석 섹션: StatePath 24→25 → 2025 체결액 순위 → 조직/People/Deal 뷰어 (+ 숨김 메뉴 2개).
- QA 섹션: Deal QC R1~R15 → 고객사 불일치 → 월별 매출신고(하위 메뉴).

### P&L 2026 (`renderBizPerfPlProgress2026`)
- API: `/performance/pl-progress-2026/summary` → 연간 T/E + 2601~2612 T/E. 현재 YYMM 헤더/셀에 `is-current-month-group`/`is-current-month` 클래스.
- Assumptions 바: 온라인/출강 공헌이익률, 월 제작/마케팅/인건비를 입력·증감 버튼으로 수정, dirty 상태는 `is-dirty` 클래스. `pnlAssumpInfoBtn` 모달에 제외 건수·snapshot_version·가정 노출, `pnlResetAssumptionsBtn`으로 기본값 복구.
- 클릭 가능 셀: 월별 E 컬럼의 REV_TOTAL/REV_ONLINE/REV_OFFLINE만 버튼(`data-pl-cell`)으로, `/performance/pl-progress-2026/deals` 호출. 정렬 recognizedAmount desc → amountUsed desc → dealName desc. variant=T는 항상 빈 결과.

### 월별 체결액 (`renderBizPerfMonthly`)
- API: `/performance/monthly-amounts/summary`(from/to=2025-01~2026-12, months 24개, rows TOTAL→CONTRACT→CONFIRMED→HIGH, segment 11종). dealCount=0 셀은 `<span class="mp-cell-btn is-zero">`.
- 하위 메뉴 edu1/edu2는 team 파라미터 전달. 셀 클릭 시 `/performance/monthly-amounts/deals`, 정렬 amount>0 → expectedAmount → dealName ASC, 모달 테이블 16컬럼(카테고리 포함) fixed colgroup.

### 문의 인입 (2팀 전용, `renderBizPerfMonthlyInquiries`)
- API: `/performance/monthly-inquiries/summary` 한 번 호출 후 클라이언트에서 규모 버튼 필터(대/중견/중소/공공/대학교/기타/미기재, 기본 대기업) 적용. 버튼 `data-inq-size` + `is-active`/`aria-pressed`.
- 테이블: sticky 2컬럼(과정포맷, 카테고리). parent 행(level1, rowKey=`<fmt>||__ALL__`)만 기본 노출, child 행(level2, rowKey=`<fmt>||<cat>`, cat=온라인/생성형AI/DT/직무별교육/스킬/기타/미기재)은 `display:none` 초기화.
- parent `<tr.inq-parent>` 클릭 → 동일 parentId child 토글, caret ▸/▾ 전환. count=0은 span.is-zero, >0은 버튼(`data-perf-kind="monthly-inquiries" data-segment data-row data-month`).
- 모달: 월별 체결액 모달 재사용, 제목만 “월별 문의 인입”, teamKey=edu2, kind="monthly-inquiries". 카테고리 컬럼 추가, 공백/null은 "미기재".
- online_first FALSE 제외는 서버에서 적용(온라인 3포맷만), 클라 필터 없음.

### 체결률 2026 (`renderBizPerfMonthlyCloseRate2026`)
- API: `/performance/monthly-close-rate/summary`(24개월, size 7×course 4, metric 6). cust(new/existing/all)·scope(all/corp_group/edu1/edu2/edu1_p1/edu1_p2/edu2_p1/edu2_p2/edu2_online) 버튼 변경 시 캐시 miss에서만 재호출.
- UI: 과정포맷별 별도 표, 행은 metrics(total→confirmed→high→low→lost→close_rate). close_rate 셀은 버튼 없음, 나머지는 값>0이면 버튼(`data-perf-kind="monthly-close-rate" data-metric ...`)으로 `/performance/monthly-close-rate/deals` 호출.
- deals 모달: rowKey=`<course>||<metric>`, metric=total|close_rate는 전체 분모, 나머지는 해당 bucket만. meta에 numerator/denominator/close_rate.

### Daily Report 2026 (Counterparty Risk)
- API: `/report/counterparty-risk?mode=offline|online`. summary.tier_groups/counts/data_quality, counterparties rows(`target_2026/coverage_2026/expected_2026/gap/coverage_ratio/pipeline_zero/evidence_bullets/recommended_actions`).
- 필터: 날짜, tier/risk 멀티, pipeline_zero 토글, 검색, 팀/파트 필터; 모두 클라이언트 상태(Map 캐시)에서 적용.
- details 토글이 evidence/추천을 펼치고 DB 버전 배지를 표시.

### Targetboard 2026 (출강/온라인)
- 데이터: `/rank/2025-top100-counterparty-dri` 1회 fetch → 클라에서 섹션별(기업교육1 1/2파트, 기업교육2 1/2파트/온라인셀) 카드 KPI 계산. 카드 8종(S0/P0/P1/P2/P3/P4/P5/N), 억 1자리 표기, override 강조. 카드 클릭 시 모달(티어/기업/카운터파티/팀&파트/담당자/26체결/26타겟).

### Counterparty DRI
- 데이터: `/rank/2025-top100-counterparty-dri` 전체 리스트 캐시. 검색 + DRI(O/X/all) + 팀/파트 필터 클라 적용. 정렬 orgWon2025 desc → cpTotal2025 desc 고정. 행 클릭 → `/rank/2025-counterparty-dri/detail`.

### 온라인 리텐션 2026
- 데이터: `/ops/2026-online-retention` → 상태 Won, 생성≥2024-01-01, 과정포맷 온라인 3종, 금액/수강시작/수강종료/코스ID 필수, end 2024-10~2027-12 범위. 섹션을 수강종료월별로 그룹핑, 정렬 endDate asc → orgName asc → dealId asc. owners는 deal.owner_json 우선, 없으면 people.owner_json.

### 딜체크/QC
- 메뉴 정의 `DEALCHECK_MENU_DEFS`: 부모 edu1/edu2, 자식 part1/part2/online. 사이드바 라벨은 깊이에 따라 `↳` 접두어(online inquiries 메뉴만 suppressArrow).
- API: `/deal-check/edu1|edu2` (또는 `/deal-check?team=`). 정렬 orgWon2025Total desc → createdAt asc → dealId asc. memoCount join, planningSheetLink는 http(s)일 때만 링크.
- 자식 메뉴는 클라에서 owners→파트 룩업(`getDealCheckPartLookup`)으로 필터. 섹션 순서: 리텐션 S0~P2 비온라인→온라인→신규 온라인→리텐션 P3~P5 온라인→비온라인→신규 비온라인.
- QC 화면: `/qc/deal-errors/summary` 카드 + `/qc/deal-errors/person` 모달. 규칙 세트는 R1~R16이 오더이며 UI는 R1~R15만 노출, issueCodes에서 R17 제거.

### 조직/People/Deal 뷰어
- 초기 데이터: `/api/initial-data`(orgs/people/deals/memos). 회사 선택 → `/orgs/{id}/people` → 사람 선택 → `/people/{id}/deals|memos`, 딜 선택 → `/deals/{id}/memos`.
- JSON 카드: `/orgs/{id}/won-groups-json` 캐시. upper_org 미선택 시 JSON 버튼 비활성 + 안내, 선택 시 전체/선택 JSON 모달, compact 버튼은 `/won-groups-json-compact`.
- 메모 모달: htmlBody 있으면 sanitizer(태그 div/table/thead/tbody/tr/th/td/caption, 링크 검증+`_blank`/`noopener`), 없으면 text pre-wrap. 테스트 `org_tables_v2_frontend.test.js`가 <br>/CRLF 정규화, JSON 버튼 활성조건을 검증한다.

### StatePath 24→25
- 서버 호출은 segment/sort/limit만 전달, 나머지 필터는 모두 클라이언트 상태(Quick Filters, 패턴 전이/셀/rail, seed/dir, risk/open/scaleUp). Snapshot/Pattern/Table/Legend/Core JSON copy가 동일 상태를 공유하며 “전체 해제”는 클라 상태만 리셋.

### 2025 체결액 순위
- 데이터: `/rank/2025-deals`만 사용, 등급 가이드/배수 설정 모달 포함. 클라에서 26 타겟/온라인/비온라인 계산. summary-by-size는 UI에서 사용하지 않음.

## Invariants (Must Not Break)
- `MENU_SECTIONS` 구조(섹션 순서/아이템 id·라벨·parentId·suppressArrow)와 `DEFAULT_MENU_ID`는 JS 상수와 동일해야 한다.
- 데스크톱: body 스크롤 없음, 사이드바·콘텐츠 분리 스크롤, 메뉴 클릭 시 `.content` scrollTop=0.
- P&L: 연간→월별 T/E 헤더, 현재 월 하이라이트, 월별 E만 버튼. assumption dirty 표시/모달 동작 유지.
- 월별 체결액/문의 인입: months 24, row/segment 고정, 0 셀 span.is-zero, 모달 정렬 amount>0→expected→name asc, 카테고리 컬럼 포함.
- 문의 인입 parent/child 토글 및 size 버튼 aria-pressed 상태 유지.
- Close-rate: 과정포맷별 표, metric 순서 고정, close_rate 셀 버튼 없음.
- DRI: orgWon2025 desc→cpTotal2025 desc 정렬, owners2025 우선순위(people.owner_json→deal.owner_json), target26 override 강조.
- 딜체크: 모든 메뉴가 동일 renderer 사용, 정렬 orgWon2025Total desc→createdAt asc→dealId asc, memoCount 0 시 비활성 버튼, planningSheetLink http(s)만 링크.
- 온라인 리텐션: start/end/amount/course_id 필수, end 2024-10~2027-12 범위 필터, 정렬 endDate asc→orgName asc→dealId asc.
- JSON/StatePath 모달/딜 모달/DRI 모달은 ESC/백드롭/X로 닫혀야 하고 공유 DOM id를 사용해야 한다.

## Coupling Map
- 프런트 상수·렌더러: `org_tables_v2.html` (`MENU_SECTIONS`, `PART_STRUCTURE`, `COUNTERPARTY_ONLINE_FORMATS`, inquiries size/order helpers, memo sanitizer 등).
- API: `org_tables_api.py`(`/performance/*`, `/rank/*`, `/statepath/*`, `/deal-check*`, `/qc/*`, `/orgs/*`) ↔ `database.py`/`statepath_engine.py`.
- 테스트: `tests/org_tables_v2_frontend.test.js` (JSON 버튼 상태, memo modal newline 정규화, auto-select), 성능/체결/문의/DRI/QC 관련 백엔드 테스트.

## Edge Cases & Failure Modes
- fetch 실패 시 섹션 루트에 muted 오류 + 토스트, 모달은 오류 텍스트만 남김.
- 캐시 잔존: DB 교체/포트 변경 시 새로고침 전까지 이전 데이터 사용.
- hash가 숨김 메뉴이면 사이드바에 없지만 렌더 가능; 잘못된 hash는 org 뷰어로 이동.
- 모달/공유 상태가 초기화되지 않으면 이전 화면 데이터가 남을 수 있음(딜 모달·JSON 캐시 재사용 주의).
- Counterparty Risk/StatePath는 클라 필터 의존도가 높아 서버 파라미터 추가 시 프런트 상태 변경이 필요.

## Verification
- 사이드바 아이템/라벨/`↳`/suppressArrow가 `MENU_SECTIONS`와 일치하고 잘못된 hash 시 org 뷰어가 열리는지 확인.
- 데스크톱에서 body 스크롤이 없고 메뉴 클릭 시 `.content`가 항상 top=0으로 리셋되는지 확인.
- `/performance/pl-progress-2026/summary` → 현재 월 하이라이트 & E 셀만 클릭 → `/performance/pl-progress-2026/deals` 정렬 확인.
- `/performance/monthly-amounts/summary` → 24개월·4 rows·segment 11종, 0 셀 span.is-zero, 모달 정렬/카테고리 열 확인.
- `/performance/monthly-inquiries/summary` → size 버튼 전환, parent/child 토글, 모달 카테고리(공백→미기재) 확인.
- Close-rate 표에서 metric 순서/버튼 상태, deals 모달 분모 규칙 확인.
- `/rank/2025-top100-counterparty-dri` → 검색/DRI/팀&파트 필터가 즉시 반영되고 정렬이 유지되는지, 행 클릭 시 detail 모달 열리는지 확인.
- `/deal-check/edu1|edu2` → 정렬/메모 버튼/partFilter 적용(자식 메뉴) 확인; planningSheetLink http(s)일 때만 링크.
- 온라인 리텐션 → endDate asc 정렬, 금액/코스ID/start/end 모두 존재하는지 확인.
- JSON/StatePath/딜 모달이 ESC/백드롭으로 닫히고 내용이 해당 데이터와 일치하는지 확인.

## Refactor-Planning Notes (Facts Only)
- 단일 HTML에 모든 로직/스타일/데이터 캐시가 들어있어 변경 영향이 광범위하다.
- 딜 모달/JSON/StatePath 모달이 공유되어 상태 충돌 위험이 있으므로 모달 초기화 유틸이 필요하다.
- 백엔드 상수(ONLINE_COURSE_FORMATS, PL_2026_TARGET 등)와 프런트 상수가 중복되어 상수 변경 시 양쪽 동기화가 필요하다.
- 성능/문의/체결률/DRI/StatePath/Targetboard가 모두 클라이언트 필터/계산을 사용하므로 서버 파라미터 추가 시 프런트 상태/캐시 구조를 함께 변경해야 한다.
