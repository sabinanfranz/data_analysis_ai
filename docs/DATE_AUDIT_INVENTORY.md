---
title: Date/Timezone Audit Inventory
last_synced: 2026-01-28
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/deal_normalizer.py
  - dashboard/server/agents/counterparty_card/agent.py
  - org_tables_v2.html
---

## Purpose
- 날짜/타임존 처리에 관여하는 모든 엔드포인트·화면·헬퍼를 전수 식별하기 위한 인벤토리.
- 목표: raw 문자열 슬라이싱/LIKE/SUBSTR 기반 연·월 판정 제거 및 KST date-only 일원화 작업의 스코프 확정.

## Backend API Inventory (날짜 필드 포함 여부)
- `/api/sizes` → 날짜 없음.
- `/api/orgs` (`list_organizations`, database.py) → 계약 체결일 연도 필터 `LIKE '2025%'` 사용 흔적(데이터 합산시) 존재.
- `/api/orgs/{org_id}/memos`, `/people/{id}/memos`, `/deals/{id}/memos` → `createdAt`(memos 테이블), 표시/정렬 시 formatDate 사용.
- `/api/orgs/{org_id}/people` → 날짜 없음.
- `/api/people/{id}/deals` (`get_deals_for_person`) → `created_at`, `contract_date`, `expected_close_date`, `start_date`, `end_date`.
- `/api/deal-check*` (`get_deal_check`) → 딜의 `created_at`, `contract_date`, `expected_close_date`, `course_start_date`, `course_end_date` 반환.
- `/api/ops/2026-online-retention` → `created_at`, `expected_close_date`, `start_date`, `end_date`, `contract_date`.
- `/api/qc/deal-errors/*` → 오류 레코드 내 `created_at`/`contract_date` 등 원본 필드 포함 가능.
- `/api/qc/monthly-revenue-report*` → 월 키 생성 시 `start_date`/`end_date` 사용.
- `/api/rank/2025-deals`, `/rank/mismatched-deals`, `/rank/2025-deals-people` → `contract_signed_date`, `expected_close_date`, `course_start_date`, `course_end_date` 포함.
- `/api/rank/won-yearly-totals`, `/rank/2025/summary-by-size`, `/rank/won-industry-summary` → 계약 체결일 연/월 집계(현재 `LIKE`/`SUBSTR` 기반).
- `/api/performance/monthly-amounts/*` → 월 키(YYMM) 생성에 계약 체결일 사용; deals 응답에 `expectedCloseDate`, `startDate`, `endDate`, `contractDate`.
- `/api/performance/monthly-inquiries/*` → 딜 생성일(“생성 날짜”)로 월 키 생성; deals 응답에 `expectedCloseDate`, `startDate`, `endDate`, `contractDate`.
- `/api/performance/pl-progress-2026/*` → 월 키(YYMM) 및 `expectedCloseDate`, `startDate`, `endDate`, `contractDate`.
- `/api/report/counterparty-risk*` → 레포트 생성·갱신 시점, 딜 `contract_signed_date`, `expected_close_date` 등 사용.
- `/api/orgs/{id}/won-groups-json*` → 딜/메모 createdAt, contract_date 포함.
- `/api/orgs/{id}/statepath*`, `/statepath/portfolio-2425` → 계약/예상/시작/종료 일자 사용.
- `/rank/2025-top100-counterparty-dri*` → `contract_signed_date`, `expected_close_date`, `course_start_date`, `course_end_date`.

## Backend Helpers with Raw Date Ops (리팩터 대상)
- `dashboard/server/database.py`
  - `_parse_date` / `_parse_date_flexible` : 문자열 분리 기반 정규화.
  - 여러 SQL에서 `LIKE '2025%'`, `SUBSTR(...,1,4)`로 연/월 판정 (`rg "LIKE '20"`, `rg "SUBSTR("` 결과 참조).
  - `_month_key_from_text`, `_date_only` 등 월/날짜 키 파생 로직 존재.
- `dashboard/server/deal_normalizer.py`
  - `_parse_date` : `"T"` split 후 날짜 부분 사용 (타임존 변환 없음).
- `dashboard/server/agents/counterparty_card/agent.py`
  - `_parse_date` : 문자열 split 기반 정규화.
- 기타: `tests/test_datetime_kst_normalization.py` 가 현재 동작을 검증(UTC→KST 경계 케이스 존재).

## Frontend Inventory (메뉴 → 사용 날짜 필드)
- 공통 포맷터: `formatDate`, `formatDateYYMMDD` in `org_tables_v2.html` — `split("T")[0]` 기반 표시.
- 메뉴/렌더러별 주요 날짜 사용:
  - 조직/People/Deal 뷰어 (`renderOrgTable`, deal 테이블) → `created_at`, `contract_date`, `expected_close_date`, `start_date`, `end_date`, memo `createdAt`.
  - 딜체크 (`renderDealCheckScreen`) → `created_at`, `contract_date`, `expected_close_date`, `course_start_date`, `course_end_date`.
  - 2026 P&L (`renderBizPerfPlProgress2026` deals 모달) → `expectedCloseDate`, `startDate`, `endDate`, `contractDate`.
  - 월별 체결액 / 문의 인입 (`renderBizPerfMonthly*` deals 모달) → 동일한 날짜 필드 셋 사용.
  - 2026 온라인 리텐션 (`renderOps2026OnlineRetention`) → `created_at`, `start_date`, `end_date`, `contract_date`, `expected_close_date`.
  - DRI/Targetboard/Counterparty screens → 계약/예상/시작/종료 일자를 상세/모달에 표시.
  - QC/메모 모달 → memo `createdAt`.
  - StatePath UI → 상태 JSON 내 `contract_date`, `expected_close_date`, `start_date`, `end_date`.

## Known Raw Date Handling Patterns (현 위치)
- 프런트: `org_tables_v2.html` `formatDate`/`formatDateYYMMDD`에서 `split("T")[0]` 문자열 절단 (라인 4262~4274).
- 백엔드: `database.py`에 `LIKE '2025%'`, `SUBSTR(d."계약 체결일",1,4)` 등 다수 (`rg "LIKE '20"`, `rg "SUBSTR("` 결과).
- 파이썬 파서: `deal_normalizer.py::_parse_date`가 ISO datetime을 `"T"` split으로 처리, 타임존 변환 없음.
- 에이전트: `agents/counterparty_card/agent.py::_parse_date`도 문자열 split 기반.

## Next Actions (for refactor phases)
- 위 인벤토리를 기반으로 PHASE 1~6 실행: KST 유틸 SSOT(date_kst.py) 추가, SQLite UDF 등록 후 모든 연/월 판정 교체, API 응답 날짜 표준화, 프런트 방어 포맷터 도입, 경계/린트 테스트 및 정책 문서 작성.

