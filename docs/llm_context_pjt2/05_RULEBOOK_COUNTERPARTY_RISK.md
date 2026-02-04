---
title: 규칙집 (PJT2) – 카운터파티 리스크 리포트 MVP
last_synced: 2026-02-04
sync_source:
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
  - org_tables_v2.html
  - tests/test_counterparty_risk_rule.py
---

# 규칙집 (PJT2) – 카운터파티 리스크 리포트 MVP

## Purpose
- 카운터파티 리스크 리포트의 포함/제외/집계/정렬/리스크 레벨 규칙을 SSOT로 정의해 재구현 가능하도록 한다.

## Behavioral Contract
- 입력은 스냅샷된 `salesmap_latest.db`로부터 D1 정규화된 `deal_norm`을 사용한다. Convert/Lost는 집계·정렬 대상에서 제외하며 날짜/금액/카운터파티 정규화는 D1 로직을 SSOT로 삼는다.
- 규칙 기반 `risk_level_rule`이 기본 노출값이며, LLM이 생성한 `risk_level_llm`은 보조 필드다.

## Invariants
- 온라인 정의: 과정포맷이 `구독제(온라인)`, `선택구매(온라인)`, `포팅` 중 하나일 때만 online(is_online=1), 그 외/NULL은 비온라인(is_nononline=1).
- 금액 선택: `금액` 우선, 없으면 `예상 체결액`; 음수/파싱 실패/빈값은 0(`amount_parse_failed`=1)으로 간주.
- deal_year: `수강시작일` 우선 → `계약 체결일` → `수주 예정일` 순으로 YYYY-MM-DD 파싱 성공 시 결정, 모두 없으면 NULL.
- 버킷: `CONFIRMED_CONTRACT` = status Won AND 필수 필드(contract_signed_date & course_start/end & course_id_raw & amount>0) 모두 존재. `CONFIRMED_COMMIT` = (status Won) OR 성사 가능성에 “확정” 토큰 포함. `EXPECTED_HIGH` = “높음” 토큰만. Lost/Convert는 None → agg_bucket=IGNORE.
- baseline_2025: 비온라인(offline 모드) 또는 온라인(online 모드) 필터 + deal_year=2025 + bucket∈{CONFIRMED_CONTRACT, CONFIRMED_COMMIT} + status!=Convert 금액 합.
- 티어: 2025 비온라인 확정액 합이 S0 ≥ 1,000,000,000, P0 ≥ 200,000,000, P1 ≥ 100,000,000, P2 ≥ 50,000,000; 조직명에 “삼성전자” 포함 시 tier=None(제외), 별도 target 가산 없음.
- target_2026: baseline_2025 × multiplier(S0=1.5, P0/P1=1.7, P2=1.5). baseline=0이면 target=0.
- coverage_2026: 모드별(is_nononline 또는 is_online) + deal_year=2026 + status NOT IN(Convert, Lost) + agg_bucket∈{CONFIRMED_*, EXPECTED_HIGH}. confirmed_2026/expected_2026 합으로 coverage 계산.
- gap = target_2026 - coverage_2026. coverage_ratio=coverage/target (target=0이면 NULL). pipeline_zero = (coverage==0 AND target>0).
- min_cov(월별): 0.05,0.10,0.15,0.20,0.25,0.30,0.40,0.50,0.60,0.75,0.90,1.00 (1~12월); severe_threshold=0.5*min_cov.
- risk_level_rule: target=0 → 양호/`rule_trigger=TARGET_ZERO`; pipeline_zero → 심각/`PIPELINE_ZERO`; else coverage_ratio<severe → 심각/`COVERAGE_BELOW_HALF_MIN`; coverage_ratio<min_cov → 보통/`COVERAGE_BELOW_MIN`; gap<=0 → 양호/`GAP_COVERED`; 그 외 양호/`ON_TRACK`.
- 정렬: risk_level_rule(심각→보통→양호) → pipeline_zero desc → tier rank(S0>P0>P1>P2) → |gap| desc → target desc.
- 요약: tier_groups(S0_P0_P1, P2)별 target/coverage/gap/coverage_ratio와 counts(severe/normal/good/pipeline_zero).
- 카드 필수: orgId/orgName/counterpartyName/tier/baseline_2025/target_2026/confirmed_2026/expected_2026/coverage_2026/gap/coverage_ratio/pipeline_zero/rule_trigger/risk_level_rule + LLM 필드(top_blockers/evidence_bullets/recommended_actions).

## Coupling Map
- 규칙 구현: `dashboard/server/deal_normalizer.py` (build_deal_norm, build_org_tier, build_counterparty_target_2026, build_counterparty_risk_rule, build_counterparty_risk_report).
- LLM 병합/폴백: `dashboard/server/counterparty_llm.py`.
- 프런트 정렬/표시는 백엔드 결과를 사용(`org_tables_v2.html` counterparty-risk-daily).

## Edge Cases
- 계약일 2025 + 수강시작일 2026 → deal_year=2026으로 잡혀 baseline_2025 제외, 2026 coverage에 포함.
- target=0 → coverage_ratio NULL, pipeline_zero=0, risk_level_rule 양호.
- counterparty 미분류 문자열은 `"미분류(카운터파티 없음)"`; excluded_by_quality=1로 표시되지만 universe/coverage에는 포함.
- Lost/Convert는 agg_bucket=IGNORE로 coverage·top_deals에서 제외.

## Verification
- 온라인/비온라인 분류: 과정포맷 3종만 is_online=1인지 `tests/test_deal_normalizer.py`로 확인.
- Lost/Convert 제외 및 버킷 분류가 agg_bucket=IGNORE인지 `tests/test_counterparty_risk_rule.py` 확인.
- target/coverage/gap/risk_level_rule 계산이 문서 식과 일치하는지 `tests/test_counterparty_risk_rule.py` 실행.
- 티어 임계값/삼성 제외가 적용되는지 `tests/test_org_tier.py` 확인.
- 연도 귀속(수강일 우선)·amount 파싱 실패 플래그는 `tests/test_deal_normalizer.py`에서 검증.

## Refactor-Planning Notes (Facts Only)
- 버킷/온라인/티어/리스크 룰이 프런트/백엔드/테스트에 모두 하드코딩되어 있어 상수 변경 시 세 계층과 문서를 동시에 수정해야 한다.
- pipeline_zero, min_cov, severe_threshold 계산은 counterparty_llm 폴백에도 사용되므로 로직 분리 시 함수 공유 또는 동일 상수 주입이 필요하다.
- 삼성전자 제외, online 3종 정의처럼 문자열 매칭 규칙이 다국어/공백 변화에 민감하므로 정규화 규칙 변경 시 회귀 테스트를 함께 추가하는 것이 안전하다.
