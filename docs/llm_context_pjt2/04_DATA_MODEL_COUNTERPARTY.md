---
title: 데이터 모델/조인 규칙 (PJT2) – 카운터파티 기준
last_synced: 2026-01-29
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
- **PRAGMA 핵심 컬럼**
  - deal: id, peopleId, organizationId, '계약 체결일', '수주 예정일', '수강시작일', '금액', '예상 체결액', '상태', '과정포맷', '성사 가능성', '코스 ID', '최근 연락일' 등(총 147 컬럼).
  - people: id, organizationId, '소속 상위 조직', 이름/연락처/최근 연락일 등(총 76 컬럼).
  - organization: id, '이름', 업종/규모/연락처 등(총 45 컬럼).
  - memo: id, text, createdAt, organizationId, peopleId, dealId 등(총 14 컬럼).
- **카운터파티 키**: (organization_id, counterparty_name); counterparty_name = people.'소속 상위 조직' 정규화, NULL/공백→'미분류(카운터파티 없음)'.
- **deal_year 계산**: course_start_date 우선, 없으면 계약 체결일, 없으면 수주 예정일.
- **비온라인 판정**: ONLINE_DEAL_FORMATS 3종(구독제(온라인), 선택구매(온라인), 포팅)만 online; 나머지/NULL은 is_nononline=1.
- **baseline_2025**: 비온라인 & deal_year=2025 & bucket∈{CONFIRMED_CONTRACT, CONFIRMED_COMMIT}, status!=Convert 합.
- **coverage_2026**: 비온라인 & deal_year=2026 & status NOT IN(Convert, Lost), confirmed+expected 금액 합.
- **메모 수집**: CounterpartyCardAgent에서 org/deal/people memo를 최근 180일, 최대 20개 dedupe 후 payload에 포함(gather_memos).
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

## Refactor-Planning Notes (Facts Only)
- signals(lost_90d_count/last_contact_date) 필드는 현재 집계되지 않고 payload에서 placeholder로 남아 있으므로 차후 추가 시 people/deal 컬럼 의존성이 필요하다.
- PRAGMA 기준 컬럼 수(Deal 98, People 76, Org 43, Memo 14)는 스냅샷 버전에 따라 달라질 수 있어 새 DB 교체 시 문서·매핑 상수 동기화가 필요하다.
- counterparty_name 정규화와 미분류 문자열은 백엔드/프런트/테스트에서 동일 상수를 사용하므로 값 변경 시 모든 계층을 함께 수정해야 한다.
