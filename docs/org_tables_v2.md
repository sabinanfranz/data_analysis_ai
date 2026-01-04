---
title: org_tables_v2 동작 정리 (FastAPI 기반)
last_synced: 2026-01-06
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - dashboard/server/json_compact.py
  - tests/test_pl_progress_2026.py
  - tests/test_perf_monthly_contracts.py
  - tests/test_api_counterparty_dri.py
  - tests/test_counterparty_llm.py
---

# org_tables_v2 동작 정리 (FastAPI 기반)

## Purpose
- 정적 프런트 `org_tables_v2.html`와 FastAPI `/api` 백엔드가 제공하는 대시보드(사업부 퍼포먼스/랭킹/StatePath/검수/QC)의 현재 계약을 코드 기준으로 기록한다.

## Behavioral Contract
- 사이드바 메뉴(최신 순서):
  - **사업부 퍼포먼스**: `2026 P&L` → `2026 월별 체결액` → `2026 Daily Report`
  - **운영 메뉴**: `2026 Target Board` → `2026 카운터파티 DRI` → 교육1/교육2 딜체크
  - **분석 메뉴**: `StatePath 24→25` → `2025 체결액 순위` → `조직/People/Deal 뷰어` (+숨김: `2025 대기업 딜·People`, `업종별 매출`)
  - **검수 메뉴**: `개인별 세일즈맵 누락/오류 딜`(id `deal-qc-r1r15`) → `고객사 불일치`
- 2026 P&L (`renderBizPerfPlProgress2026`):
  - API `/performance/pl-progress-2026/summary?year=2026`. 컬럼: 연간(T/E) 후 2601~2612 T/E, 행: 매출/공헌비용/공헌이익/고정비/OP/영업이익률.
  - 숫자 소수 1자리, 항목 좌정렬·나머지 우정렬, 현재 월 컬럼 하이라이트. 연간 컬럼 비활성, 월별 E(총/온라인/출강)만 버튼, 0이면 span. 드릴다운 `/performance/pl-progress-2026/deals?year=2026&month=YYMM&rail=TOTAL|ONLINE|OFFLINE&variant=E`, 모달은 테이블-only 숫자 우정렬(tabular-nums).
- 2026 월별 체결액 (`renderBizPerfMonthly`):
  - API `/performance/monthly-amounts/summary?from=2025-01&to=2026-12`. Rows TOTAL→CONTRACT→CONFIRMED→HIGH, 24개월 고정, 억 단위 1자리. 0은 비활성 span, 버튼 클릭 시 `/performance/monthly-amounts/deals`.
  - 드릴다운 모달: 테이블-only, 첫 4컬럼 좌정렬·숫자 우정렬, 합계 카드 없음.
- StatePath 24→25: 헤더 1줄(필터 버튼+칩+전체 해제), segment=전체 기본. 전체 해제 시 segment 리셋 후 `/statepath/portfolio-2425` 재호출. 스냅샷 6타일 1행 가로 스크롤.
- QC(개인별 세일즈맵 누락/오류 딜 `renderDealQcR1R15Screen`):
  - 요약: 3분할 카드(교육1/교육2/공공), 컬럼=담당자/총이슈(내림차순), 데이터는 `/qc/deal-errors/summary?team=edu1|edu2|public`.
  - 상세 모달: 행 클릭 시 `/qc/deal-errors/person?owner=...&team=...`. R1~R15 섹션만 표시(위배 없으면 섹션 미출력). Deal/Org/People 링크, table-layout fixed + colgroup 공통 폭. ESC/백드롭/X로 닫힘.
- 기타 화면: DRI/랭킹/불일치/Dealcheck/Org 뷰어 등은 동일 렌더러와 `/rank/*`, `/orgs/*`, `/deal-check/*` 등 API 사용.

## Invariants (Must Not Break)
- 메뉴 라벨·순서 위의 4섹션 구분 유지, id 불변(`biz-perf-pl-progress-2026`, `biz-perf-monthly`, `counterparty-risk-daily`, `deal-qc-r1r15`, 등).
- P&L: 연간→월별 컬럼 순, 숫자 1자리, 현재 월 하이라이트, 월별 E 버튼만 활성, 온라인 판정 리스트(구독제/선택구매/포팅) 고정.
- 월별 체결액: rows TOTAL/CONTRACT/CONFIRMED/HIGH, 24개월 키 모두 출력, 0은 비활성(span), 드릴다운 테이블-only.
- 모달 공통: 테이블-only, 숫자 우정렬(tabular-nums), 가로 스크롤, ESC/백드롭/X 닫힘.
- QC 요약: 팀별 3그리드, 총이슈 desc 기본, 15s 타임아웃 에러 노출. 상세: 위배 없는 룰 섹션 미출력, 위배 없으면 “위배된 규칙이 없습니다.”, colgroup 공통 폭 유지.

## Coupling Map
- 프런트: `org_tables_v2.html` (렌더러들: `renderBizPerfPlProgress2026`, `renderBizPerfMonthly`, `renderCounterpartyRiskDaily`, `renderRankCounterpartyDriScreen`, `renderDealQcR1R15Screen`, 등) + CSS(테이블/모달/그리드) + 링크 빌더(salesmap*Url).
- API: `dashboard/server/org_tables_api.py` (`/performance/*`, `/rank/*`, `/statepath/portfolio-2425`, `/qc/deal-errors/*`, `/deal-check/*`, `/orgs/*`).
- 로직/DB: `dashboard/server/database.py` (P&L/월별 집계, DRI, QC R1~R15 룰/예외, 온라인 포맷, 티어/확정액), `statepath_engine.py`, `json_compact.py`.
- 테스트: `tests/test_pl_progress_2026.py`, `tests/test_perf_monthly_contracts.py`, `tests/test_api_counterparty_dri.py`, `tests/test_counterparty_llm.py`.

## Edge Cases & Failure Modes
- API 실패 시 `fetchJson` 예외 → 본문 오류 메시지 + 토스트, 모달도 오류 텍스트만.
- 데이터 없음: 각 화면 “데이터가 없습니다.” 표시(표/카드 미렌더). 월별/DRI/QC 모두 동일.
- P&L/월별: 쿼리 실패 시 muted 오류, 합계 0이면 퍼센트 null. 월별 course_id 없으면 fallback 쿼리.
- QC: “비매출입과” 이름 포함/생성일<2024-10-01/팀 외 담당자/owner 없음은 meta.dq로 제외. 15s 타임아웃으로 지연 시 에러 표시. 위배 없는 룰 섹션은 숨김.
- 메뉴 hash가 유효하지 않으면 `DEFAULT_MENU_ID`(`org-view`)로 이동.

## Verification
- 사이드바 라벨/순서: 사업부 퍼포먼스→운영→분석→검수 섹션이 위 명칭/순서대로 노출.
- P&L: `/performance/pl-progress-2026/summary` 호출 성공, 연간→월별 컬럼 순서·숫자 1자리, 현재월 하이라이트, 월별 E 버튼만 클릭 가능, 드릴다운 테이블-only.
- 월별 체결액: `/performance/monthly-amounts/summary` 후 rows 4개·24개월, 0셀 비활성, 버튼 → `/performance/monthly-amounts/deals`.
- QC 요약: `/qc/deal-errors/summary?team=edu1|edu2|public` 3건 완료, 담당자/총이슈 내림차순 표시, 행 클릭 시 상세 호출.
- QC 상세: R1~R15 중 위배 있는 룰만 섹션 표시, Deal/Org/People 링크 정상, ESC/백드롭/X로 닫힘, 열 폭 균일(colgroup).
- 기타: StatePath 필터/전체 해제 동작, 불일치/DRI/Dealcheck 화면 로드 시 콘솔 에러 없는지.

## Refactor-Planning Notes (Facts Only)
- QC 룰 계산(`database.py::_qc_compute`)과 프런트 렌더(`renderDealQcR1R15Screen`)에 규칙/예외가 분산되어 있어 변경 시 양쪽 동시 수정 필요.
- `org_tables_v2.html` 단일 파일에 다수 렌더러/CSS/모달이 혼재되어 영향 범위가 큼. 공통 모달 DOM을 공유하므로 구조 변경 시 다른 화면에도 영향 가능.
- API_BASE는 origin+/api 기본, 로컬 기본값 `http://localhost:8000/api`; 배포 환경 변경 시 프런트 상수 수정 필요.
