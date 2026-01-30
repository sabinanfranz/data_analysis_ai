---
title: 용어집 (PJT2)
last_synced: 2026-01-29
sync_source:
  - salesmap_latest.db
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/agents/counterparty_card/agent.py
---

# 용어집 (PJT2)

## Purpose
- 카운터파티 리스크 리포트(MVP)에서 사용하는 핵심 용어/키/해시를 정규화해, 재구현 시 혼동을 방지한다.

## Behavioral Contract
- 모든 정의는 실제 DB 스키마(PRAGMA)와 구현 파일(deal_normalizer.py, counterparty_llm.py, report_scheduler.py)에 근거한다.
- 빈값/NULL 처리 규칙(예: 카운터파티 미분류)은 규칙집/데이터 모델 문서를 일관되게 따른다.

## Invariants
- **카운터파티 키**: `(organizationId, counterpartyName)`; `counterpartyName = people."소속 상위 조직"` 정규화, 공백/NULL→`"미분류(카운터파티 없음)"` (`COUNTERPARTY_UNKNOWN`).
- **온라인/비온라인**: 온라인 과정포맷 3종(`구독제(온라인)`, `선택구매(온라인)`, `포팅`)만 online, 나머지/NULL은 비온라인(is_nononline=1).
- **확정/예상 버킷**: `CONFIRMED_CONTRACT`, `CONFIRMED_COMMIT`(확정), `EXPECTED_HIGH`(예상). Convert/Lost는 agg_bucket=IGNORE로 coverage/baseline 집계에서 제외.
- **target_2026**: 카운터파티 2025 확정액 × 티어 multiplier(S0=1.5, P0/P1=1.7, P2=1.5). 삼성전자 이름 포함 시 target=50억(하드코딩). baseline=0이면 target=0.
- **coverage_2026**: 2026 비온라인, status NOT IN (Convert, Lost), bucket∈{CONFIRMED_*, EXPECTED_HIGH} 금액 합(confirmed+expected). `gap = target_2026 - coverage_2026`, `coverage_ratio = coverage/target`(target=0→NULL), `pipeline_zero = coverage==0 AND target>0`.
- **rule_risk_level**: target=0→양호; pipeline_zero→심각; else coverage_ratio<severe_threshold(=0.5*min_cov)→심각; coverage_ratio<min_cov(월별)→보통; gap<=0→양호; 그 외 양호.
- **LLM 필드**: `risk_level_llm`, `top_blockers`, `evidence_bullets(3)`, `recommended_actions(2~3)`은 카드 에이전트 출력/폴백, 규칙 레벨을 덮지 않음.
- **해시/버전**: `db_signature = mtime-size`(scheduler), `db_hash = sha256(db mtime) 16hex`(deal_normalizer), `llm_input_hash = sha256(canonical payload)`(CounterpartyCard), `prompt_version = v1`.

## Coupling Map
- DB: `people."소속 상위 조직"`, `deal."상태"`, `"과정포맷"`, `"금액"`, `"예상 체결액"`, `"계약 체결일"`, `"수주 예정일"`, `"수강시작일"`, `"성사 가능성"`, `organization."이름"`.
- 코드: `deal_normalizer.py`(정규화/타겟/리스크), `counterparty_llm.py`(payload/hash/폴백), `report_scheduler.py`(캐시/락/cron).

## Invariants
- **카운터파티 키**: `(organizationId, counterpartyName)`; `counterpartyName = people."소속 상위 조직"` 정규화, 공백/NULL→`"미분류(카운터파티 없음)"`(`COUNTERPARTY_UNKNOWN` in `deal_normalizer.py`).
- **온라인/비온라인**: 과정포맷 3종(`구독제(온라인)`, `선택구매(온라인)`, `포팅`)만 online, 나머지/NULL은 비온라인(`is_nononline=1`) (`deal_normalizer.py`, `counterparty_card/agent.py`).
- **버킷**: `CONFIRMED_CONTRACT`, `CONFIRMED_COMMIT`, `EXPECTED_HIGH`; Lost/Convert는 agg_bucket=IGNORE로 coverage/baseline 집계 제외 (`deal_normalizer.py` D4).
- **target_2026**: baseline_2025 × multiplier(S0=1.5, P0/P1=1.7, P2=1.5); baseline=0→target=0; 조직명이 "삼성전자"면 50억 하드코딩 (`deal_normalizer.py`).
- **coverage_2026**: 2026 비온라인, status NOT IN(Convert, Lost), agg_bucket∈{CONFIRMED_*, EXPECTED_HIGH}; `gap = target_2026 - coverage_2026`, `coverage_ratio = coverage/target`(target=0→NULL), `pipeline_zero = coverage==0 && target>0`.
- **risk_level_rule**: target=0→양호; pipeline_zero→심각; coverage_ratio<severe_threshold(0.5*min_cov)→심각; coverage_ratio<min_cov(월별)→보통; gap<=0→양호; else 양호.
- **LLM 필드**: `risk_level_llm`, `top_blockers`, `evidence_bullets(3)`, `recommended_actions(2~3)`는 카드 에이전트 산출/폴백이며 규칙 레벨을 덮지 않는다.
- **해시/버전**: `db_signature=mtime-size`(report_scheduler), `db_hash=sha256(db mtime)[:16]`(deal_normalizer), `llm_input_hash=sha256(canonical payload)`(CounterpartyCard), `prompt_version=v1`.

## Edge Cases
- `counterpartyName` 공백/NULL → `"미분류(카운터파티 없음)"`.
- `target_2026=0` → coverage_ratio NULL, rule_risk_level 양호.
- LLM 미호출/실패 시 risk_level_llm가 규칙값으로 대체, evidence/actions는 폴백 생성.

## Verification
- PRAGMA에서 필요한 컬럼이 실제 존재하는지 확인: `PRAGMA table_info('deal'|'people'|'organization'|'memo')`.
- 규칙집(05)과 구현(deal_normalizer.py)에서 용어 사용이 일치하는지 grep 확인.
- `counterparty_llm.compute_llm_input_hash`가 동일 payload에서 재사용되는지, memo 변경 시 hash 변경되는지 확인.

## Refactor-Planning Notes (Facts Only)
- signals(lost_90d_count/last_contact_date)는 현재 집계되지 않고 payload 필드만 존재(counterparty_llm.py); 추후 집계 추가 시 문서/코드 동시 수정 필요.
