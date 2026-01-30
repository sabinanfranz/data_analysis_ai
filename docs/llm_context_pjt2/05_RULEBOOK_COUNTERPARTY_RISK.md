---
title: 규칙집 (PJT2) – 카운터파티 리스크 리포트 MVP
last_synced: 2026-01-29
sync_source:
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
  - dashboard/server/database.py
  - org_tables_v2.html
---

# 규칙집 (PJT2) – 카운터파티 리스크 리포트 MVP

## Purpose
- 카운터파티 리스크 리포트의 포함/제외/집계/정렬/리스크 레벨 규칙을 SSOT로 정의해 재구현 가능하도록 한다.

## Behavioral Contract
- 입력은 salesmap_latest.db(정규화 deal_norm 기준). Convert/Lost 제외, 비온라인만 대상, 날짜/금액/카운터파티 정규화는 D1 로직을 신뢰한다.
- 규칙 risk_level이 UI 기본이며, LLM 레벨은 참고용이다.

## Invariants
- 온라인 정의: `구독제(온라인)`, `선택구매(온라인)`, `포팅`만 online; 나머지/NULL은 비온라인(is_nononline=1).
- 금액 선택: 금액 있으면 사용, 없으면 예상 체결액, 실패/빈값→0 (`amount_parse_failed`).
- deal_year: course_start_date 우선, 없으면 계약 체결일, 없으면 수주 예정일.
- 버킷: CONFIRMED_CONTRACT/CONFIRMED_COMMIT(확정), EXPECTED_HIGH(예상); Lost/Convert는 agg_bucket=IGNORE.
- baseline_2025: 비온라인, deal_year=2025, bucket∈{CONFIRMED_CONTRACT, CONFIRMED_COMMIT}, status!=Convert 합계.
- 티어: S0≥10억, P0 2~<10억, P1 1~<2억, P2 0.5~<1억; 삼성전자 이름 포함 시 tier=None, target=50억 하드코딩.
- target_2026: baseline×multiplier(S0=1.5, P0/P1=1.7, P2=1.5); baseline=0→target=0.
- coverage_2026: 비온라인, deal_year=2026, status NOT IN(Convert, Lost), bucket∈{CONFIRMED_*, EXPECTED_HIGH}; confirmed+expected 합.
- gap = target_2026 - coverage_2026; coverage_ratio=coverage/target (target=0→NULL); pipeline_zero = coverage==0 && target>0.
- min_cov(월별): 1~12월 0.05/0.10/0.15/0.20/0.25/0.30/0.40/0.50/0.60/0.75/0.90/1.00; severe_threshold=0.5*min_cov.
- risk_level_rule: target=0→양호; pipeline_zero→심각; coverage_ratio<severe_threshold→심각; coverage_ratio<min_cov→보통; gap<=0→양호; else 양호.
- 정렬: risk_level_rule(심각→보통→양호) → pipeline_zero desc → tier rank(S0>P0>P1>P2) → |gap| desc → target desc.
- 요약: tier_groups(S0~P1, P2)별 target/coverage/gap/coverage_ratio, counts(severe/normal/good/pipeline_zero).
- 카드 필수: org/counterparty/tier/baseline/target/confirmed/expected/coverage/gap/coverage_ratio/pipeline_zero/rule_trigger/risk_level_rule + LLM 필드(top_blockers/evidence_bullets 3/recommended_actions 2~3).
- 온라인 정의: `구독제(온라인)`, `선택구매(온라인)`, `포팅`만 online, 나머지/NULL은 비온라인(is_nononline=1).
- 금액 선택: 금액 있으면 사용, 없으면 예상 체결액, 실패/빈값→0(`amount_parse_failed` 플래그).
- deal_year: `course_start_date` 우선, 없으면 `계약 체결일` → `수주 예정일`.
- 버킷: `CONFIRMED_CONTRACT`(Won+필수필드+금액>0), `CONFIRMED_COMMIT`(Won 또는 확정), `EXPECTED_HIGH`(높음, Lost/Convert 제외). Convert/Lost는 agg_bucket=IGNORE.
- 2025 기준액(카운터파티 baseline_2025): 비온라인, deal_year=2025, bucket ∈ {CONFIRMED_CONTRACT, CONFIRMED_COMMIT}, status != Convert, 합계.
- 티어: 조직 2025 확정액 기준 S0>=10억, P0 2~<10억, P1 1~<2억, P2 0.5~<1억, 삼성전자 이름 포함 시 제외(None).
- target_2026: baseline_2025 × multiplier(S0=1.5, P0/P1=1.7, P2=1.5), baseline=0이면 target=0.
- 2026 coverage: 비온라인, deal_year=2026, status!=Convert/Lost. confirmed_2026=CONFIRMED_* 합, expected_2026=EXPECTED_HIGH 합, coverage_2026=둘 합.
- gap: target_2026 - coverage_2026. coverage_ratio=coverage/target (target=0이면 NULL).
- pipeline_zero: coverage_2026==0 AND target_2026>0.
- 월별 최소 커버리지(min_cov): Jan 0.05, Feb 0.10, Mar 0.15, Apr 0.20, May 0.25, Jun 0.30, Jul 0.40, Aug 0.50, Sep 0.60, Oct 0.75, Nov 0.90, Dec 1.00. severe_threshold=0.5*min_cov.
- risk_level_rule: target=0 → 양호; pipeline_zero → 심각; else coverage_ratio<severe→심각, <min_cov→보통, gap<=0 또는 나머지→양호.
- 정렬 우선순위: risk_level_rule(심각→보통→양호) → pipeline_zero desc → tier rank(S0>P0>P1>P2) → gap abs desc → target desc.
- 요약: tier 그룹 S0~P1 / P2 각각 target/coverage/gap/coverage_ratio, 상태 칩(심각/보통/양호/pipeline_zero 카운트).
- 카드 필수 필드: org/counterparty/tier/baseline/target/confirmed/expected/coverage/gap/coverage_ratio/pipeline_zero/rule_trigger/risk_level_rule + LLM 필드(top_blockers/evidence_bullets 3/recommended_actions 2~3).

## Coupling Map
- 규칙 구현: `dashboard/server/deal_normalizer.py` (build_deal_norm, build_org_tier, build_counterparty_target_2026, build_counterparty_risk_rule, build_counterparty_risk_report).
- LLM 병합/폴백: `dashboard/server/counterparty_llm.py`.
- 프런트 정렬/표시는 백엔드 결과를 사용(`org_tables_v2.html` counterparty-risk-daily).

## Edge Cases
- 계약일 2025 + 수강시작일 2026 → deal_year=2026, 2025 합계 제외, 2026 coverage에 포함.
- target=0 → coverage_ratio NULL, risk_level_rule 양호.
- counterparty 미분류 → excluded_by_quality=1, 여전히 universe/coverage에 포함하되 기본 랭킹에서 필터 가능.
- Lost 딜은 coverage 집계에서 배제(agg_bucket=IGNORE).

## Verification
- 온라인/비온라인 분류: 과정포맷 3종만 online인지 테스트.
- Lost/Convert 제외: agg_bucket이 IGNORE로 표시되어 coverage/baseline에서 빠지는지 확인.
- target/coverage/gap/risk_level_rule 계산이 코드와 일치하는지 `tests/test_counterparty_risk_rule.py` 실행.
- 티어 산정(S0~P2) 및 삼성 50억 특례가 적용되는지 `tests/test_org_tier.py` 확인.
- 온라인/비온라인 분류 테스트: 과정포맷 3종만 is_nononline=False인지 확인.
- 연도 귀속 테스트: 계약 2025/수강 2026 → 2026으로 귀속되는지 D4 테스트로 검증.
- Convert/Lost 제외: deal_norm/pipeline 집계에서 포함되지 않는지 확인.
- target/coverage/gap/risk_level_rule 계산이 문서 식과 일치하는지 `tests/test_counterparty_risk_rule.py` 실행.
- 티어 산정이 S0~P2 임계값/삼성 제외를 지키는지 `tests/test_org_tier.py` 확인.

## Refactor-Planning Notes (Facts Only)
- 버킷/온라인/티어/리스크 룰이 프런트/백엔드/테스트에 모두 하드코딩되어 있어 상수 변경 시 세 계층과 문서를 동시에 수정해야 한다.
- pipeline_zero, min_cov, severe_threshold 계산은 counterparty_llm 폴백에도 사용되므로 로직 분리 시 함수 공유 또는 동일 상수 주입이 필요하다.
- 삼성전자 제외, online 3종 정의처럼 문자열 매칭 규칙이 다국어/공백 변화에 민감하므로 정규화 규칙 변경 시 회귀 테스트를 함께 추가하는 것이 안전하다.

