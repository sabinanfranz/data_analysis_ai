---
title: org_tables_v2 프런트 계약
last_synced: 2026-01-06
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - tests/test_pl_progress_2026.py
  - tests/test_perf_monthly_contracts.py
---

## Purpose
- 정적 프런트 `org_tables_v2.html`의 메뉴/상태/렌더/캐시/모달 계약을 코드 기준으로 명세한다.

## Behavioral Contract
- 사이드바: `MENU_SECTIONS` 정의 순서로 사업부 퍼포먼스(2026 P&L → 2026 월별 체결액 → 2026 Daily Report(WIP)) → 운영(2026 Target Board, 2026 카운터파티 DRI, 딜체크 7개 메뉴) → 분석(StatePath 24→25, 2025 체결액 순위, 조직/People/Deal 뷰어, 숨김: 2025 대기업 딜·People/업종별 매출) → 검수(개인별 세일즈맵 검수, 고객사 불일치). 해시가 유효하지 않으면 `DEFAULT_MENU_ID="org-view"`. 딜체크 메뉴는 단일 config(`DEALCHECK_MENU_DEFS`)에서 부모 2개(교육1/교육2)와 자식 5개(교육1: 1/2파트, 교육2: 1/2파트/온라인셀)를 정의하며, 사이드바에서는 부모/자식 모두 동일 정렬로 보여주되 자식 라벨에만 `↳ ` 접두어를 추가한다.
- API_BASE: origin이 있으면 `<origin>/api`, 아니면 `http://localhost:8000/api`.
- 2026 P&L (`renderBizPerfPlProgress2026`):
  - `/performance/pl-progress-2026/summary` → 연간(T/E) 후 2601~2612 T/E 컬럼을 렌더. 현재 월 헤더/셀에 `is-current-month-group`/`is-current-month` 클래스 부여.
  - assumptions 바(공헌이익률 온라인/출강, 월 제작/마케팅/인건비) 입력 → `applyAssumptionsToPnlData`로 즉시 재계산. `pnlAssumpInfoBtn`은 meta.excluded·snapshot_version·가정을 모달로 표시, `pnlResetAssumptionsBtn`은 기본값으로 복구.
  - 월별 E 열(REV_TOTAL/REV_ONLINE/REV_OFFLINE)만 클릭 가능, `/performance/pl-progress-2026/deals` 결과를 recognizedAmount desc→amountUsed desc→dealName asc 정렬해 모달 테이블로 표시.
- 2026 월별 체결액 (`renderBizPerfMonthly`):
  - `/performance/monthly-amounts/summary` → YYMM 24개월, rows TOTAL→CONTRACT→CONFIRMED→HIGH, segment 11종. 값은 `formatEok1`로 억 1자리, dealCount=0이면 `<span class="mp-cell-btn is-zero">` 비활성.
  - 셀 클릭 시 `/performance/monthly-amounts/deals`, amount>0 우선→expectedAmount→dealName asc 정렬 후 모달 테이블(15열, colgroup 고정) 표시.
- 카운터파티 DRI (`renderRankCounterpartyDriScreen`):
  - `/rank/2025-top100-counterparty-dri`를 캐시 후 검색/DRI(O/X/all)/팀&파트/미입력 upper_org 숨김/정렬(default|cp_online_desc|cp_offline_desc) 필터를 클라이언트에서 적용. 행 클릭 시 `/rank/2025-counterparty-dri/detail`.
- 딜체크/QC:
  - `renderDealCheckScreen(teamKey, options)` 한 곳에서 7개 딜체크 메뉴를 공통 렌더하며, `/deal-check?team=edu1|edu2` 결과를 orgWon2025Total desc→createdAt asc→dealId asc로 렌더, memoCount=0이면 “메모 없음” 비활성 버튼. 부모 메뉴는 필터 없이 팀 전체를, 자식 메뉴는 `partFilter`(1/2파트/온라인셀)를 받아 owners→`getDealCheckPartLookup` 룩업 기반으로 클라이언트 필터를 적용한다. 섹션은 공통 6분할(리텐션 S0~P2 비온라인→온라인→신규 온라인→리텐션 P3~P5 온라인→비온라인→신규 비온라인) 순서를 유지한다.
  - `renderDealQcR1R15Screen`은 `/qc/deal-errors/summary` 카드(팀별 총이슈 desc) + `/qc/deal-errors/person` 상세 모달(R1~R15 위배만 표시) 제공.
- 조직/People/Deal 뷰어:
  - `getSizes`→`/orgs`로 조직 목록 로드, 선택 시 `/orgs/{id}/people`→사람 선택→`/people/{id}/deals`/`/people/{id}/memos`/`/deals/{id}/memos`.
  - 상위 조직 JSON 카드: `/orgs/{id}/won-groups-json` 캐시 → 선택 upper_org가 없으면 JSON 버튼 비활성+안내, 선택 시 전체/선택 JSON 모달, compact 버튼은 `/won-groups-json-compact`.
- StatePath 24→25: `/statepath/portfolio-2425` 결과를 필터 칩+요약 카드+테이블로 렌더, “전체 해제” 버튼이 segment/search/필터를 초기화해 재호출.

## Invariants (Must Not Break)
- 메뉴 섹션/라벨/순서/ID는 `MENU_SECTIONS` 정의와 일치해야 하며, 잘못된 hash 시 org-view로 이동해야 한다.
- P&L 테이블: 연간(T/E) → 월별(T/E) 순, 현재 월 하이라이트, 월별 E만 클릭 가능, 숫자 우측 정렬(tabular-nums), 0은 버튼 대신 span.
- 월별 체결액: rows 4개·YYMM 24개 전부 출력, dealCount=0 셀은 비활성 span, 금액은 `formatEok1`(원→억) 사용.
- 모달 공유 DOM(`#rankPeopleModal*`, `#dealQcModal`, JSON/StatePath 모달)을 재사용하며 ESC/백드롭/X로 닫혀야 한다.
- 캐시: fetchJson이 path별 Map에 저장, 무효화 없음 → DB 교체/포트 변경 시 새로고침 필수. 딜체크 7개 메뉴는 모두 `DEALCHECK_MENU_DEFS`에서 파생된 동일 renderer를 사용해야 하며, 메뉴 추가 시 config 1곳만 수정하면 사이드바/renderer가 함께 반영돼야 한다.

## Coupling Map
- 프런트: `org_tables_v2.html` 렌더러/상수(`MENU_SECTIONS`, `DEFAULT_MENU_ID`, `PART_STRUCTURE`, `COUNTERPARTY_ONLINE_FORMATS` 등).
- API: `dashboard/server/org_tables_api.py`(`/performance/*`, `/rank/*`, `/statepath/*`, `/deal-check*`, `/qc/*`, `/orgs/*`) ↔ `dashboard/server/database.py`/`statepath_engine.py`.
- 테스트: `tests/test_pl_progress_2026.py`, `tests/test_perf_monthly_contracts.py`가 P&L/월별 계약을, `tests/test_api_counterparty_dri.py`가 DRI 집계를 검증한다.

## Edge Cases & Failure Modes
 - fetch 실패 시 각 섹션 루트에 muted 오류 문구, 토스트 표시. 모달은 로딩 텍스트로 초기화 후 실패 시 오류 문구만 남는다.
 - 캐시로 인해 DB 교체 후 새로고침 전까지 이전 데이터가 남는다.
 - hash가 숨김 메뉴 id(`rank-2025-people`, `industry-2025`)일 때도 렌더는 되지만 사이드바에 표시되지 않는다.
 - 선택 초기화 시 People/Deal/메모/JSON 상태가 모두 리셋되어야 하며, 누락 시 이전 데이터가 잔류할 수 있다.

## Verification
 - 사이드바 라벨/순서가 계약대로인지, 잘못된 hash 시 조직 뷰어가 열리는지 확인한다.
- `/performance/pl-progress-2026/summary` 응답으로 연간→월별 T/E 헤더와 현재 월 하이라이트가 표시되고, 월별 E 셀 클릭 시 `/performance/pl-progress-2026/deals` 모달이 recognizedAmount desc 정렬인지 확인한다.
- `/performance/monthly-amounts/summary`가 24개월·4개 row를 모두 포함하고 0 셀이 비활성화되며, 모달 정렬이 amount>0→expectedAmount→dealName asc인지 확인한다.
- `/rank/2025-top100-counterparty-dri` 호출 후 검색/DRI/팀&파트/정렬 필터가 즉시 반영되고 행 클릭 시 `/rank/2025-counterparty-dri/detail` 모달이 열리는지 확인한다.
- 딜체크 메뉴 7개가 모두 표시되고, `/deal-check?team=edu1|edu2` 결과가 orgWon2025Total desc→createdAt asc→dealId asc 정렬인지 확인한다. 자식 메뉴(파트/온라인셀)는 owners 기반 partFilter가 적용돼 카운트/목록이 달라지는지 검증한다.
- 상위 조직 JSON 카드에서 선택 없을 때 버튼 비활성+안내, 선택 후 전체/선택 JSON/compact 모달이 올바른 데이터를 표시하는지 확인한다.

## Refactor-Planning Notes (Facts Only)
 - `org_tables_v2.html` 단일 파일에 메뉴/렌더러/모달/CSS가 모두 포함되어 구조 변경 시 전 화면에 영향이 퍼진다.
 - 모달 DOM과 fetch 캐시를 여러 화면이 공유해 상태 충돌 위험이 있으며, 정리되지 않은 상태가 다른 화면에 잔류할 수 있다.
 - 온라인 판정/타겟 상수 등이 백엔드와 중복돼 있어 규칙 변경 시 JS/파이썬 양쪽을 동시에 수정해야 한다.
