---
title: org_tables_v2 프런트 계약
last_synced: 2025-12-26
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - tests/test_pl_progress_2026.py
  - tests/test_perf_monthly_contracts.py
---

# org_tables_v2 프런트 계약

## Purpose
- 프런트 `org_tables_v2.html`의 메뉴/상태/렌더/스타일 계약을 리팩터링 시 준수할 수 있도록 문서화한다.

## Behavioral Contract
- 메뉴/상태: 사이드바 메인 섹션 `사업부 퍼포먼스`는 “2026 P&L”(id `biz-perf-pl-progress-2026`) → “2026 월별 체결액”(id `biz-perf-monthly`). 이후 Target Board, Counterparty DRI, 체결액 순위, Org Viewer, 교육 1/2팀 딜체크, StatePath 24→25, 고객사 불일치. `MENU_RENDERERS`에 매핑된 렌더 함수를 호출하며 state.activeMenuId로 제어.
- 2026 P&L (`renderBizPerfPlProgress2026`):
  - `/performance/pl-progress-2026/summary?year=2026` → 연간 T/E + 2601~2612 T/E. 숫자 소수 1자리, 항목만 좌측 정렬. 현재 월 컬럼 하이라이트. 연간 컬럼 클릭 불가, 월별 E(총/온라인/출강)만 버튼(0은 비활성).
  - Drilldown `/performance/pl-progress-2026/deals?year=2026&month=YYMM&rail=TOTAL|ONLINE|OFFLINE&variant=E`: 모달 테이블-only, 첫 4컬럼 좌측, 숫자 우측 tabular-nums, 헤더 sticky만 유지(모달 헤더), thead는 static.
- 2026 월별 체결액 (`renderBizPerfMonthly`):
  - `/performance/monthly-amounts/summary?from=2025-01&to=2026-12`, rows TOTAL/CONTRACT/CONFIRMED/HIGH, 세그먼트 라벨 한글. 24개월 고정. 금액 1자리 억, 0이면 비활성. 클릭 시 `/performance/monthly-amounts/deals`.
  - Drilldown 모달: 테이블-only, 첫 4컬럼 좌측, 숫자 우측 tabular-nums, 카드 없음.
- StatePath 24→25: 헤더 1줄(필터 CTA+칩+전체 해제), 전체 해제 시 segment=전체로 리셋 후 `/statepath/portfolio-2425` 재호출. 필터 버튼은 Drawer 토글, sessionStorage hint pulse 1회.
- 기타: 랭킹/DRI/TargetBoard/Dealcheck/OrgViewer/불일치는 해당 렌더 함수와 `/rank/*`, `/orgs/*`, `/statepath/portfolio-2425` API를 사용.

## Invariants (Must Not Break)
- Sidebar perf 라벨/순서 고정: 2026 P&L → 2026 월별 체결액.
- P&L 테이블: columns 연간T/E 후 월별 2601~2612 T/E; 숫자 1자리; 항목 좌/그 외 우; 현재 월 하이라이트; 연간 비활성; 월별 E(총/온라인/출강)만 클릭.
- P&L 온라인 판정 리스트(백엔드): 구독제(온라인)/구독제 (온라인)/선택구매(온라인)/선택구매 (온라인)/포팅만 온라인. PL_2026_TARGET offline 값 변경 시 UI 자동 반영.
- 월별 체결액 rows=TOTAL/CONTRACT/CONFIRMED/HIGH, 24개월 모두 포함, 세그먼트 라벨 그대로 노출.
- 모달 공유 DOM `#dealsModalBackdrop/#dealsModalTitle/#dealsModalSubtitle/#dealsModalBody`; 카드/합계 없음; 숫자 우측 정렬 tabular-nums.
- StatePath 헤더 구조/전체 해제 동작 유지; segment 리셋 후 fetch는 필수.

## Coupling Map
- 프런트: `org_tables_v2.html` (MENU_SECTIONS, renderBizPerfPlProgress2026, renderBizPerfMonthly, modal CSS `.deals-modal-wide`, `.pnl-table`, `.mp-deals-table`).
- API: `dashboard/server/org_tables_api.py` → `dashboard/server/database.py` (get_pl_progress_summary/deals, get_perf_monthly_amounts_summary/deals) → SQLite tables `deal`, `organization`, `people`.
- StatePath: `org_tables_v2.html` loaders ↔ `dashboard/server/statepath_engine.py` ↔ `/statepath/portfolio-2425`.
- 테스트: `tests/test_pl_progress_2026.py` (P&L targets/recognition), `tests/test_perf_monthly_contracts.py` (monthly buckets/segments).

## Edge Cases & Failure Modes
- P&L summary excludes deals missing start/end or valid amount; meta.excluded에 카운트. Percent 연간은 총매출 0이면 null. Variant T drilldown은 빈 리스트.
- Monthly summary skips month-less deals; course_id 컬럼 없으면 fallback 쿼리.
- Fetch 실패 시 muted 에러 문구+toast, 재시도 없음. 모달 재사용으로 이전 내용이 잠시 보일 수 있음(로드 중 텍스트로 초기화).
- 메뉴 hash 불일치 시 DEFAULT_MENU_ID=`org-view`.

## Verification
- 사이드바 perf 섹션 라벨/순서: 2026 P&L → 2026 월별 체결액; 클릭 시 정상 렌더.
- P&L 테이블: 연간 앞, 현재 월 하이라이트, 숫자 1자리 우측 정렬, 연간 클릭 불가·월별 E 총/온라인/출강만 클릭, 타겟 offline 2608_T=21.6 확인.
- P&L 모달: 헤더+X 버튼 상단, 내부 스크롤, 테이블-only, 숫자 우측 tabular-nums.
- 월별 체결액: rows 4개, 24개월 모두, 0 비활성, 세그먼트 라벨 한국어 유지, 모달 테이블-only.
- StatePath: 헤더 CTA+칩+전체 해제, 전체 해제 시 segment=전체로 fetch.
- API 존재 확인: `/performance/pl-progress-2026/summary|deals`, `/performance/monthly-amounts/summary|deals`.

## Refactor-Planning Notes (Facts Only)
- P&L 스타일/정렬/하이라이트 로직이 프런트 JS+CSS에 분산; 백엔드는 숫자만 반환(1자리 포맷은 프런트 책임).
- 모달 DOM/핸들 공유로 구조 변경 시 월별/P&L 모달 모두 영향.
- 온라인 판정/타겟 상수는 백엔드, 포맷/하이라이트는 프런트에 있어 규칙 변경 시 양방향 수정 필요.
