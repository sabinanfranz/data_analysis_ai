---
title: SQLite 데이터 모델 핵심 필드
last_synced: 2026-02-04
sync_source:
  - dashboard/server/database.py
  - salesmap_first_page_snapshot.py
  - org_tables_v2.html
  - tests/test_won_groups_json.py
---

## Purpose
- FastAPI/프런트가 참조하는 SQLite 스냅샷 스키마의 핵심 필드와 사용처를 요약한다.

## Behavioral Contract
- 스냅샷 스크립트(`salesmap_first_page_snapshot.py`)가 Salesmap API 응답을 그대로 TEXT 컬럼으로 적재하며, 백엔드(`database.py`)는 필요한 컬럼만 선택해 집계/정렬한다.
- 스키마는 동적으로 확장 가능(없던 컬럼을 발견하면 `TableWriter`가 ALTER TABLE)하나, 주요 집계는 아래 열이 존재한다고 가정한다.

## Invariants (Must Not Break)
- 공통 키: 모든 테이블의 `id`는 TEXT, organizationId/peopleId 외래키는 공백 시 제외된다.
- organization: `"이름"`, `"기업 규모"`, `"업종"`, `"업종 구분(대)"`, `"업종 구분(중)"`, `"팀"`, `"담당자"`, `"전화"` 필드를 사용하며, `"이름"`이 비면 id로 대체한다.
- people: `"이름"`, `"소속 상위 조직"`, `"팀(명함/메일서명)"`, `"직급(명함/메일서명)"`, `"담당 교육 영역"`, `"제출된 웹폼 목록"`을 사용한다. 공백 upper_org/team은 `"미입력"`으로 정규화된다.
- deal: `"상태"`, `"금액"`, `"예상 체결액"`, `"계약 체결일"`, `"수주 예정일"`, `"수강시작일"`, `"수강종료일"`, `"과정포맷"`, `"카테고리"`, `"담당자"`, `"생성 날짜"`, `"LOST 확정일"`, `"이탈 사유"`, `"코스 ID"`(있을 경우)를 사용한다.
- memo: `organizationId`/`peopleId`/`dealId`, `text`, `ownerId`, `createdAt`/`updatedAt` 필드를 사용하며, `_get_owner_lookup`으로 ownerId→name 매핑한다. `htmlBody` 컬럼이 존재할 수 있으며, 존재 시 메모 조회/원본 won-groups-json에서 함께 노출되지만 compact 변환에서는 제거된다.
- webform_history(후처리): `peopleId`, `webFormId`, `createdAt`를 사용해 webform 제출 날짜를 매핑한다.

## Coupling Map
- 적재: `salesmap_first_page_snapshot.py` TableWriter가 API 응답을 SQLite에 append/ALTER한다.
- 조회/집계: `dashboard/server/database.py`가 PRAGMA table_info로 존재 열을 확인 후 집계(`_detect_course_id_column`, `_pick_column`).
- 프런트: `org_tables_v2.html`이 `/api/*` 응답을 그대로 렌더하며, webforms/memos는 won-groups-json에 포함되어 UI 모달로 노출된다.
- 테스트: `tests/test_won_groups_json.py`, `tests/test_perf_monthly_contracts.py`, `tests/test_pl_progress_2026.py`가 필수 컬럼 존재 여부와 fallback을 검증한다.

## Edge Cases & Failure Modes
- course_id 컬럼이 없으면 월별 체결액 집계가 fallback 쿼리(`NULL AS course_id`)로 진행되고 summary만 계산된다.
- webform_history 테이블이 없으면 webform 제출 날짜 매핑은 건너뛰지만 won-groups-json 생성은 계속된다.
- 금액/날짜 파싱 실패 시 해당 딜/메모는 집계에서 제외되어 totals가 줄어들 수 있다.

## Verification
- SQLite에서 `PRAGMA table_info`로 organization/people/deal/memo/webform_history 필드가 존재하는지 확인한다.
- `/api/orgs/{id}/won-groups-json` 응답에 industry_major/mid, webforms 날짜, cleanText 메모가 포함되는지 샘플 org로 호출한다.
- course_id 컬럼이 없는 DB에서도 `/api/performance/monthly-amounts/summary`가 오류 없이 동작하는지 확인한다.
- webform_history 미존재 DB에서 호출 시 날짜가 `"날짜 확인 불가"`로 처리되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 필드 존재 여부에 따라 fallback 경로가 다르게 실행되므로 스키마 변경 시 테스트 케이스를 함께 조정해야 한다.
- webform_history는 후처리로만 생성되어 스냅샷 크롤 실패 시 비어 있을 수 있으며, 프런트는 날짜 부재를 `"날짜 확인 불가"`로 처리한다.
