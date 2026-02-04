---
title: 용어집 (PJT2)
last_synced: 2026-02-04
sync_source:
  - salesmap_latest.db
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/agents/counterparty_card/agent.py
---

# 용어집 (PJT2)

## Purpose
- 카운터파티 리스크 리포트에서 사용하는 핵심 용어/키/해시를 PRAGMA와 구현 코드 기반으로 정리한다.

## Behavioral Contract
- 모든 정의는 실제 DB 스키마와 구현 파일(deal_normalizer.py, counterparty_llm.py, report_scheduler.py, counterparty_card/agent.py)에 근거한다.
- 빈값/NULL 처리 규칙(예: 카운터파티 미분류)은 규칙집/데이터 모델 문서와 일관되게 유지한다.

## Invariants
- **카운터파티 키**: `(organizationId, counterpartyName)`; `counterpartyName = people."소속 상위 조직"` 정규화, 공백/NULL → `"미분류(카운터파티 없음)"`(`COUNTERPARTY_UNKNOWN`).
- **온라인/비온라인**: 과정포맷 3종(`구독제(온라인)`, `선택구매(온라인)`, `포팅`)만 online, 나머지/NULL은 비온라인(`is_nononline=1`).
- **버킷**: `CONFIRMED_CONTRACT`(Won + 필수 필드 + amount>0), `CONFIRMED_COMMIT`(Won 또는 성사 가능성에 "확정" 포함), `EXPECTED_HIGH`("높음"만). Lost/Convert는 agg_bucket=IGNORE로 집계 제외.
- **target_2026**: baseline_2025 × multiplier(S0=1.5, P0/P1=1.7, P2=1.5), baseline=0이면 target=0. 조직명에 "삼성전자" 포함 시 tier=None으로 제외(별도 금액 가산 없음).
- **coverage_2026**: 모드별(offline=is_nononline, online=is_online) + deal_year=2026 + status NOT IN(Convert, Lost) + agg_bucket∈{CONFIRMED_*, EXPECTED_HIGH}; `gap = target_2026 - coverage_2026`, `coverage_ratio = coverage/target`(target=0→NULL), `pipeline_zero = coverage==0 AND target>0`.
- **risk_level_rule**: target=0→양호/TARGET_ZERO; pipeline_zero→심각/PIPELINE_ZERO; coverage_ratio<0.5*min_cov→심각; coverage_ratio<min_cov→보통; gap<=0→양호; 그 외 양호/ON_TRACK.
- **LLM 필드**: `risk_level_llm`, `top_blockers`, `evidence_bullets(3)`, `recommended_actions(2~3)`는 CounterpartyCardAgent 출력/폴백으로, 규칙 risk_level을 덮지 않는다.
- **해시/버전**: `db_signature = mtime-size`(scheduler), `db_hash = sha256(db mtime)[:16]`(deal_normalizer), `llm_input_hash = sha256(canonical payload)`(CounterpartyCard), `prompt_version = v1`.

## Coupling Map
- DB 컬럼: `people."소속 상위 조직"`, `deal."상태"`, `"과정포맷"`, `"금액"`, `"예상 체결액"`, `"계약 체결일"`, `"수주 예정일"`, `"수강시작일"`, `"성사 가능성"`, `organization."이름"`.
- 코드: `deal_normalizer.py`(정규화/타겟/리스크), `counterparty_llm.py`/`agents/counterparty_card/agent.py`(payload/hash/폴백), `report_scheduler.py`(캐시/락/cron).

## Edge Cases
- counterpartyName 공백/NULL → `"미분류(카운터파티 없음)"` + excluded_by_quality=1.
- target_2026=0 → coverage_ratio NULL, risk_level_rule 양호.
- LLM 미호출/실패 시 risk_level_llm가 규칙값으로 대체되고 evidence/actions는 폴백 생성.

## Verification
- PRAGMA로 컬럼 존재 확인: `PRAGMA table_info('deal'|'people'|'organization'|'memo')`.
- ONLINE_DEAL_FORMATS, COUNTERPARTY_UNKNOWN, BUCKET 상수가 코드/테스트/문서에서 동일한지 `rg`로 확인.
- `counterparty_llm.compute_llm_input_hash`가 동일 payload에서 재사용되고 memo 변경 시 hash가 변경되는지 확인.

## Refactor-Planning Notes (Facts Only)
- signals(lost_90d_count/last_contact_date)는 현재 집계되지 않는 placeholder이므로, 실제 신호 집계 추가 시 hash/캐시 invalidation이 발생한다.
- counterparty_unknown 문자열을 변경하면 백엔드/프런트/테스트/문서 전체를 동시 수정해야 한다.
