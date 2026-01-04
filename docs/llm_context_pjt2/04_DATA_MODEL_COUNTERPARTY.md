---
title: 데이터 모델/조인 규칙 (PJT2) – 카운터파티 기준
last_synced: 2026-01-10
sync_source:
  - salesmap_latest.db
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
---

# 데이터 모델/조인 규칙 (PJT2) – 카운터파티 기준

## Purpose
- 카운터파티 리스크 리포트에서 사용하는 키/조인/필수 컬럼을 PRAGMA 근거로 명확히 정의해 재구현 시 혼동을 방지한다.

## Behavioral Contract
- 카운터파티 키: `(organizationId, counterparty_name)`이며 `counterparty_name = people."소속 상위 조직"` 정규화 결과. NULL/공백은 `"미분류(카운터파티 없음)"`.
- deal 1행=1 deal 유지, Convert/Lost 제외 규칙은 룰집(D5)와 동일하게 적용.
- 메모 수집 시 organization/deal/people 연결을 모두 합쳐 중복 제거한다.

## Invariants
- PRAGMA(실측):
  - `deal` TEXT 컬럼(발췌): `id`, `peopleId`, `organizationId`, `"이름"`, `"상태"`, `"과정포맷"`, `"금액"`, `"예상 체결액"`, `"계약 체결일"`, `"수주 예정일"`, `"수강시작일"`, `"수강종료일"`, `"코스 ID"`, `"성사 가능성"`, `"최근 연락일"` 등(총 98개).
  - `people` TEXT 컬럼(발췌): `id`, `organizationId`, `"이름"`, `"소속 상위 조직"`, `"팀(명함/메일서명)"`, `"직급(명함/메일서명)"`, `"담당 교육 영역"`, `"제출된 웹폼 목록"`, `"최근 연락일"` 등(총 76개).
  - `organization` TEXT 컬럼(발췌): `id`, `"이름"`, `"기업 규모"`, `"업종"`, `"업종 구분(대)/(중)"`, `"담당자"`, `"팀"` 등(총 43개).
  - `memo` TEXT 컬럼: `id`, `text`, `dealId`, `peopleId`, `organizationId`, `ownerId`, `createdAt`, `updatedAt`.
- counterparty_name 정규화: `_normalize_str` 후 NULL/공백 → `"미분류(카운터파티 없음)"` (deal_normalizer.py).
- is_nononline: 온라인 과정포맷 3종 제외 나머지/NULL은 비온라인.
- deal_year: `course_start_date` 우선, 없으면 계약/수주 예정일에서 연도 추출.

## Coupling Map
- 정규화: `dashboard/server/deal_normalizer.py` (build_deal_norm)에서 counterparty_name, is_nononline, amount/date/bucket 결정.
- LLM 메모 수집: `dashboard/server/counterparty_llm.py`에서 org/deal/people 메모 합집합, 최근 180일/20개.
- API/리포트: `deal_normalizer.build_counterparty_risk_report` → `counterparty_name`과 org join을 그대로 사용.

## Edge Cases
- `peopleId` 없음 또는 people 조인 실패 → counterparty_name = "미분류(카운터파티 없음)", `counterparty_missing_flag=1`.
- `organizationId` NULL → org_name `(미상)`으로 보정, 티어/집계에서 제외.
- 날짜 파싱 실패 → deal_year NULL, dq_year_unknown에 반영(집계 제외).
- amount 파싱 실패/빈값 → 0, `amount_parse_failed=1`, 품질 경고.

## Verification
- PRAGMA 명령으로 컬럼 존재 확인:  
  `python - <<'PY'\nimport sqlite3;conn=sqlite3.connect('salesmap_latest.db');\nfor t in ['deal','people','organization','memo']:\n print(t, [r[1] for r in conn.execute(f\"PRAGMA table_info('{t}')\")]);\nPY`
- counterparty 정규화가 `"미분류(카운터파티 없음)"`으로 통일되는지 deal_normalizer의 counterparty_missing_flag 로직을 확인.
- 메모 연결: org/deal/people 경로에서 180일/20개, 중복 제거가 적용되는지 counterparty_llm.gather_memos 확인.
