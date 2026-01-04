---
title: 구현 파이프라인 (PJT2) – D1~D7
last_synced: 2026-01-10
sync_source:
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/org_tables_api.py
  - tests/test_counterparty_risk_rule.py
---

# 구현 파이프라인 (PJT2) – D1~D7

## Purpose
- D1~D7을 실제 실행 순서/입출력/임시 테이블/아이템포턴시/폴백 관점으로 정리해 재실행·운영 시 참조한다.

## Behavioral Contract
- 입력: `salesmap_latest.db` 스냅샷(스케줄러가 복사). 출력: `report_cache/YYYYMMDD.json`(원자적 저장) + `report_cache/llm/...`(LLM 캐시) + status.json.
- 모든 단계는 idempotent; 캐시가 동일(as_of+db_signature)하면 재계산을 스킵한다.
- 실패 시 최근 성공본을 그대로 제공(폴백), LLM 실패는 전체 실패로 처리하지 않는다.

## Invariants (Must Not Break, 단계별)
- **D1 deal_norm (TEMP)**: Convert 제외, amount/date parse, is_nononline, counterparty_name 정규화, pipeline_bucket(확정/예상) 설정. dq_metrics 수집.
- **D2 org_tier_runtime (TEMP)**: 2025 비온라인 확정액 합 → 티어(S0/P0/P1/P2, 삼성 제외), confirmed_amount_2025_won 포함.
- **D3 counterparty_target_2026 (TEMP)**: 유니버스(2025/2026 비온라인) × 티어 org → baseline_2025, target_2026, is_unclassified flag.
- **D4 tmp_counterparty_risk_rule (TEMP)**: 2026 coverage(확정/예상), target join, gap/coverage_ratio/pipeline_zero, risk_level_rule(min_cov/월), rule_trigger.
- **D5 report JSON**: build_counterparty_risk_report → counterparty 카드 정렬 + 요약 + data_quality + meta(db_version hash, as_of, generated_at).
- **D6 LLM 병합**: counterparty_llm.generate_llm_cards → payload hash→캐시 hit→폴백 evidence/actions. 규칙 risk_level 우선, LLM 필드 병합. **deal_norm을 재조회하지 않고 D5에서 만든 `top_deals_2026` 리스트를 사용**(없으면 deal 테이블 간단 fallback).
- **D7 스케줄/캐시**: run_daily_counterparty_risk_job (report_scheduler) → DB 안정성 체크(3분 윈도우, 재시도) → 스냅샷 → 캐시 존재 시 스킵 → 생성/atomic write → status.json 업데이트 → retention.

## Coupling Map
- 파이프라인/임시테이블: `dashboard/server/deal_normalizer.py` (build_deal_norm/org_tier/target/risk_rule/report).
- LLM 캐시/폴백: `dashboard/server/counterparty_llm.py`.
- 스케줄/락/캐시/상태: `dashboard/server/report_scheduler.py`.
- API: `dashboard/server/org_tables_api.py` (`/api/report/counterparty-risk`, `/recompute`, `/status`).
- 프런트: `org_tables_v2.html`(`counterparty-risk-daily` fetch/render).
- 테스트: `tests/test_counterparty_risk_rule.py`(D4), `tests/test_counterparty_target.py`, `tests/test_org_tier.py`, `tests/test_deal_normalizer.py`.

## Edge Cases
- DB 최신 수정이 3분 미만이면 DB_UNSTABLE로 재시도 후 실패 시 status에 FAILED 기록, 캐시 기존본 유지.
- 캐시 쓰기 실패 시 기존 캐시 보존, status에 CACHE_WRITE_FAILED 필요(추가 개선 포인트).
- LLM 캐시 파일이 깨졌거나 prompt_version 변경 시 재생성; 실패 시 폴백 evidence/actions 생성.
- deal_norm TEMP 테이블 스코프: build_counterparty_risk_report 내부 커넥션에서만 사용, LLM은 counterparty row에 포함된 top_deals_2026을 사용해 재조회하지 않음.

## Verification
- 로컬 생성 예시:  
  `python - <<'PY'\nfrom dashboard.server.report_scheduler import run_daily_counterparty_risk_job\nprint(run_daily_counterparty_risk_job(force=True))\nPY`
- 캐시 확인: `report_cache/YYYYMMDD.json` meta.as_of/db_signature 존재 여부, llm 캐시 폴더 생성 여부.
- 단위테스트: `PYTHONPATH=. python3 -m unittest tests.test_deal_normalizer tests.test_org_tier tests.test_counterparty_target tests.test_counterparty_risk_rule`.
- 스냅샷 사용 여부: report_work/salesmap_snapshot_* 존재 확인.
