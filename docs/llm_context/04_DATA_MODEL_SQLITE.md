---
title: SQLite 데이터 모델 핵심 필드
last_synced: 2026-02-04
sync_source:
  - dashboard/server/database.py
  - salesmap_first_page_snapshot.py
  - org_tables_api.py
  - org_tables_v2.html
---

## Purpose
- FastAPI(`dashboard/server/database.py`, `org_tables_api.py`)와 프런트(`org_tables_v2.html`)가 의존하는 SQLite 스냅샷(`salesmap_latest.db`)의 **실제 사용 컬럼**과 파싱 규칙을 SSOT로 기록한다.

## Behavioral Contract
- 스냅샷 생성: `salesmap_first_page_snapshot.py`가 Salesmap API 응답을 **모든 필드 TEXT**로 저장하며, 새 필드는 `TableWriter`가 `ALTER TABLE ... ADD COLUMN <col> TEXT`로 append-only 추가한다.
- 백엔드 조회: 각 기능은 필요 컬럼이 없으면 `_pick_column`/`_has_column`으로 대체 컬럼을 찾거나 해당 기능을 스킵한다. 숫자/날짜 파싱 실패 시 해당 행은 건너뛰거나 0/None으로 대체된다.
- 날짜 파싱: 기본 `DATE_KST_MODE=legacy`(문자열 접두 4자리 연도, `LIKE 'YYYY%'`). `shadow/strict` 모드에서는 `date_kst.kst_year/kst_yymm`로 파싱하며, 파싱 실패 시 행 제외.
- 금액 파싱: `float(...)` 실패 시 0.0 취급. 일부 집계는 `금액`이 없으면 `예상 체결액`(expected_amount)으로 대체한다.

## Invariants (Must Not Break)
- 기본 키: 모든 테이블 `id`는 TEXT. 관계 키 `organizationId`/`peopleId`/`dealId`/`leadId`는 공백/NULL이면 무시된다.
- organization 필수 사용 컬럼: `id`, `"이름"`(없으면 id), `"기업 규모"`, `"업종"`, `"업종 구분(대)"`, `"업종 구분(중)"`, `"팀"`, `"담당자"`(JSON), 연락처 `"전화"`. 이 컬럼이 없으면 `/api/orgs` 및 rank/statepath 집계가 깨진다.
- people 필수 사용 컬럼: `id`, `organizationId`, `"이름"`, `"소속 상위 조직"`, `"팀(명함/메일서명)"`, `"직급(명함/메일서명)"`, `"담당 교육 영역"`, `"제출된 웹폼 목록"`, `"담당자"`(owner JSON). 없으면 won-groups-json grouping, org people 뷰, webform 매핑이 동작하지 않는다.
- deal 필수 사용 컬럼: `id`, `peopleId`, `organizationId`, `"상태"`, `"금액"`, `"예상 체결액"`, `"계약 체결일"`, `"수주 예정일"`, `"수강시작일"`, `"수강종료일"`, `"과정포맷"`, `"카테고리"`, `"담당자"`(owner JSON), `"생성 날짜"`, `"LOST 확정일"`, `"이탈 사유"`, `"코스 ID"`(있으면). 결측 시 각 집계/필터에서 해당 행을 제외하거나 NULL로 노출한다.
- memo 필수 사용 컬럼: `id`, `organizationId`/`peopleId`/`dealId`, `text`, `ownerId`, `createdAt`, `updatedAt`; `htmlBody`가 있으면 원본 메모 조회 시 포함되지만 compact/markdown 변환에서 제거된다.
- webform_history 필수 사용 컬럼: `peopleId`, `webFormId`, `createdAt`; 없으면 webform 날짜는 "날짜 확인 불가"로 표시된다.

## Coupling Map (기능 → 컬럼)
- 목록/검색 `/api/orgs`: `organization.(id,"이름","기업 규모","팀","담당자")`, won2025 계산 시 `deal."금액"`, `deal."계약 체결일"`, 상태 `Won`.
- People 목록 `/api/orgs/{id}/people`: `people.(id,"이름","소속 상위 조직","팀(명함/메일서명)","직급(명함/메일서명)","담당 교육 영역","이메일","전화")` + deal_count 조인.
- Memos `/api/orgs/{id}/memos`, `/people/{id}/memos`, `/deals/{id}/memos`: `memo.(id,text,htmlBody?,ownerId,createdAt,updatedAt,dealId,peopleId,organizationId)` + owner 이름 매핑용 `organization/people/deal."담당자"` JSON.
- Won grouping `/api/orgs/{id}/won-groups-json`:
  - org meta: `organization.("기업 규모","업종","업종 구분(대)","업종 구분(중)")`
  - people: `people.("소속 상위 조직","팀(명함/메일서명)","직급(명함/메일서명)","담당 교육 영역","제출된 웹폼 목록")`
  - deals: `deal.("상태","성사 가능성","수주 예정일","예상 체결액","LOST 확정일","이탈 사유","과정포맷","카테고리","계약 체결일","금액","수강시작일","수강종료일","Net(%)","담당자","생성 날짜")`
  - memos: `memo.(text,htmlBody?,createdAt,ownerId)` filtered by org/people/deal
  - webform dates: `webform_history.(peopleId,webFormId,createdAt)`
- Compact/Markdown (`json_compact.py`, `markdown_compact.py`): uses won-groups-json 출력 후
  - 날짜: `contract_date/start_date/end_date/created_at/expected_date/lost_confirmed_at` → `YYYY-MM-DD`
  - 금액: `amount` 또는 `expected_amount` float 변환
  - memo 정리: `cleanText` 우선, 없으면 `text`; phone redact, truncate 240 chars
  - day1_teams: `deal.team` JSON을 `day1_teams`로 정규화
- 성과 집계 (`performance` 계열):
  - 월별 체결액: `deal.("계약 체결일","예상 체결액","금액","상태","성사 가능성","수주 예정일","수강시작일","수강종료일","과정포맷","카테고리","코스 ID")`
  - 문의 인입: 동일 deal set에서 `month=생성 날짜/계약/예상` 파싱, 필터 `size_group`은 organization."기업 규모", `course_format`은 deal."과정포맷", `category_group`은 deal."카테고리"에서 파생
  - 체결률: 위 컬럼 + `owner_names`(담당자 JSON 파싱) + 기존 고객 리스트 파일(EXISTING_2024_FOR_2025*)
  - P&L 진행율매출(2026): `deal.("상태","금액","예상 체결액","수강시작일","수강종료일","성사 가능성","과정포맷","담당자")`
- Deal Check/QC: `_pick_column`으로 `기획시트 링크`, `코스 ID`, `수주 예정일`, `예상 체결액`, `계약 체결일`, `수강시작일`, `수강종료일`, `과정포맷/카테고리`, `online_cycle/online_first`, `instructor_*`, `proposal_*` 등을 선택; 누락되면 NULL 필드로 노출.
- Ops 2026 온라인 리텐션: deal `status=Won`, 기간 2024-10-01~2027-12-31, 필드 `과정포맷`, 온라인 입과 주기/최초 여부, 수강시작/종료일, 금액, 소속 상위 조직, 팀 서명, memoCount.
- StatePath 24→25: Won 딜(2024/2025)에서 `contract_date`/`created_at`/`expected_amount`, `people."소속 상위 조직"`, `deal."과정포맷"`, `organization."기업 규모"` 사용하여 cell/rail 계산.

## Edge Cases & Failure Modes
- 컬럼 미존재: `_pick_column`이 None이면 해당 기능 필드가 NULL로 노출되거나 행이 필터링됨(예: `코스 ID` 없음 → P&L/리텐션 일부 지표 누락, `기획시트 링크` 없음 → deal-check planningSheetLink NULL).
- 날짜 파싱 실패: `kst_yymm`/`kst_year` 실패 시 행 제외; close-rate/inquiries 집계의 해당 월 카운트에서 빠진다.
- 금액이 0/None: 일부 집계가 `expected_amount`로 대체하지만 여전히 0이면 제외; P&L에서는 금액/예상 모두 없으면 `missing_amount` 카운트에 포함되어 제외된다.
- webform_history 테이블이 없거나 peopleId/webFormId 빈값: 제출 날짜는 "날짜 확인 불가"로 노출, UI는 그대로 표시.

## Verification
- 핵심 컬럼 존재 확인
  ```bash
  sqlite3 salesmap_latest.db <<'SQL'
  PRAGMA table_info(organization);
  PRAGMA table_info(people);
  PRAGMA table_info(deal);
  PRAGMA table_info(memo);
  PRAGMA table_info(webform_history);
  SQL
  ```
- Won 그룹 응답 샘플
  ```bash
  curl -s "http://localhost:8000/api/orgs/<org_id>/won-groups-json" | jq '.organization, .groups[0].people[0], .groups[0].deals[0]'
  ```
  - industry_major/mid, webforms.date, memos.cleanText/htmlBody 제거 여부 확인
- 성과 집계 파싱 확인
  ```bash
  curl -s "http://localhost:8000/api/performance/monthly-amounts/summary?from=2025-01&to=2025-02" | jq '.months, .segments[0].rows[0].byMonth'
  ```
  - months 키가 YYMM으로 채워지고 금액이 0이 아닌지 확인

## Refactor-Planning Notes (Facts Only)
- `_pick_column` 후보 리스트가 기능별로 분산되어 있어 스키마 변경 시 영향도 파악이 어렵다 → 공통 매핑 테이블화 필요.
- 금액/날짜 파싱 실패 로깅이 제한적이라 집계 누락 원인 추적이 어렵다 → 파싱 실패 수집/메타 노출 검토.
- webform_history는 후처리(best-effort)라 크롤 실패 시 데이터가 비어 있음 → 파이프라인 재시도/알림 통합 필요.
