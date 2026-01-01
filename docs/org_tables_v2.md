---
title: org_tables_v2 동작 정리 (FastAPI 기반)
last_synced: 2025-12-26
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - dashboard/server/json_compact.py
  - tests/test_pl_progress_2026.py
  - tests/test_perf_monthly_contracts.py
---

# org_tables_v2 동작 정리 (FastAPI 기반)

## Purpose
- 정적 프런트 `org_tables_v2.html`와 FastAPI 백엔드(`/api`)가 제공하는 사업부 퍼포먼스/랭킹/StatePath/딜체크 UI의 현재 계약을 리팩터블하게 기록한다.

## Behavioral Contract
- 메뉴(사이드바): 사업부 퍼포먼스 섹션은 `2026 P&L`(id `biz-perf-pl-progress-2026`) → `2026 월별 체결액`(id `biz-perf-monthly`) 순. 이후 `2026 Target Board` → `2025 카운터파티 DRI` → `2025 체결액 순위` → `조직/People/Deal 뷰어` → `교육 1팀 딜체크` → `교육 2팀 딜체크` → `StatePath 24→25` → (서브) `고객사 불일치`.
- 2026 P&L (`renderBizPerfPlProgress2026`):
  - API `/performance/pl-progress-2026/summary?year=2026` → 컬럼은 연간(T/E) 후 월별 2601~2612 T/E, 행은 매출/공헌비용/공헌이익/고정비/OP/영업이익률.
  - 숫자 표기: 모든 값 소수 1자리 고정, 항목만 좌측 정렬·그 외 우측 정렬, 현재 월 컬럼 하이라이트. 연간 컬럼은 비활성, 월별 E(총/온라인/출강)만 버튼, 0이면 비활성 span.
  - 드릴다운: `/performance/pl-progress-2026/deals?year=2026&month=YYMM&rail=TOTAL|ONLINE|OFFLINE&variant=E`, 모달은 테이블만, 숫자 우측 정렬(tabular-nums).
- 2026 월별 체결액 (`renderBizPerfMonthly`):
  - API `/performance/monthly-amounts/summary?from=2025-01&to=2026-12`, 세그먼트 라벨 한글 유지. Rows TOTAL→CONTRACT→CONFIRMED→HIGH, 24개월(2501~2612) 고정, 금액 억 단위 1자리. 0은 비활성 span, 그 외 버튼 → `/performance/monthly-amounts/deals`.
  - Drilldown 모달: 테이블만, 첫 4컬럼 좌측 정렬, 숫자 우측 정렬(tabular-nums), 합계 카드 없음.
- StatePath 24→25: 헤더에 필터 CTA+칩+전체 해제 한 줄(타이틀 없음). 전체 해제 클릭 시 segment=전체로 리셋하고 `/statepath/portfolio-2425` 재호출. Snapshot 6타일 1행 고정(가로 스크롤).
- 기타 화면: 랭킹/DRI/TargetBoard/Dealcheck/Org 뷰어/불일치 등은 `org_tables_v2.html` 동일 렌더러와 `org_tables_api.py`의 `/rank/*`, `/statepath/portfolio-2425`, `/orgs/*` API를 사용.

## Invariants (Must Not Break)
- 메뉴 라벨/순서: 사업부 퍼포먼스 = 2026 P&L → 2026 월별 체결액 (org_tables_v2.html: MENU_SECTIONS).
- P&L 테이블: 컬럼 순서 연간T/E → 2601~2612 T/E; 숫자 1자리; 항목 좌/나머지 우 정렬; 현재 월 컬럼 하이라이트; 연간 컬럼 클릭 불가, 월별 E(총/온라인/출강)만 클릭 (renderBizPerfPlProgress2026).
- P&L 온라인 판정 리스트: 구독제(온라인)/구독제 (온라인)/선택구매(온라인)/선택구매 (온라인)/포팅만 온라인 (database.py::_is_online_for_pnl). PL_2026_TARGET offline 값은 상수 그대로 사용.
- 월별 체결액: rows TOTAL/CONTRACT/CONFIRMED/HIGH 고정, 24개월 모두 존재, 세그먼트 라벨 한국어 유지 (database.py:get_perf_monthly_amounts_summary).
- 모달: 공유 DOM `#dealsModal*`, 테이블-only, 숫자 우측 정렬 tabular-nums, 폭 최대 min(96vw,1400px) 내부 스크롤, 카드/요약 없음 (org_tables_v2.html modal CSS/openBizPerfDealsModal/openPlProgressDealsModal).
- StatePath: 전체 해제 시 segment=전체로 리셋 후 fetch; 헤더 CTA/칩/전체 해제 한 줄 유지 (org_tables_v2.html).

## Coupling Map
- 프런트: `org_tables_v2.html` (renderers, CSS `.pnl-table`, `.mp-monthly-table`, `.deals-modal-wide`).
- API: `dashboard/server/org_tables_api.py` (`/performance/pl-progress-2026/*`, `/performance/monthly-amounts/*`, `/rank/*`, `/statepath/portfolio-2425`).
- DB/로직: `dashboard/server/database.py` (P&L progress calc, PL_2026_TARGET, monthly perf loader, segment labels), `dashboard/server/statepath_engine.py`.
- 테스트: `tests/test_pl_progress_2026.py`, `tests/test_perf_monthly_contracts.py`.

## Edge Cases & Failure Modes
- P&L summary excludes deals with missing start/end, non-positive amount/expected, invalid range; counts in `meta.excluded`. Percent 연간 값은 총매출 0이면 null. Variant T drilldown 즉시 빈 리스트.
- 월별 체결액 로더: month_key 없음 스킵; course_id 컬럼 없으면 fallback 쿼리로 재시도.
- 모달 fetch 실패 시 muted 오류 메시지와 toast; 재시도 없음.
- 메뉴 hash가 유효하지 않으면 DEFAULT_MENU_ID=`org-view`.

## Verification
- 사이드바: 사업부 퍼포먼스 내 라벨/순서가 2026 P&L → 2026 월별 체결액.
- P&L 테이블: 연간 컬럼 먼저, 현재 월 컬럼 하이라이트, 숫자 1자리 우측 정렬, 연간 셀 비활성·월별 E 셀만 클릭, 타겟 offline 2608_T=21.6 확인.
- P&L 모달: 헤더+X 버튼 상단, 테이블-only, 숫자 우측 정렬 tabular-nums, 가로 스크롤 정상.
- 월별 체결액: rows 4개, 24개월 키 모두, 0 셀 비활성, 모달 테이블-only.
- StatePath: 헤더 CTA+칩+전체 해제; 전체 해제 후 segment=전체로 fetch.
- API 엔드포인트 확인: `/performance/pl-progress-2026/summary|deals`, `/performance/monthly-amounts/summary|deals`.

## Refactor-Planning Notes (Facts Only)
- P&L 스타일/정렬/하이라이트 로직이 JS와 CSS 양쪽에 분산되어 있음 (`renderBizPerfPlProgress2026`, `.pnl-table`).
- 모달 DOM/핸들(`state.rankPeopleModal`)을 여러 화면이 공유, 구조 변경 영향 범위 큼.
- P&L 타겟/온라인 판정 상수는 백엔드에만, 포맷/하이라이트 규칙은 프런트에만 존재(규칙 중복/분산 가능성).
