---
title: 구현 파이프라인 (PJT2) – D1~D7
last_synced: 2026-01-20
sync_source:
  - dashboard/server/deal_normalizer.py
  - dashboard/server/agents/registry.py
  - dashboard/server/agents/core/orchestrator.py
  - dashboard/server/report/composer.py
  - dashboard/server/counterparty_llm.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/org_tables_api.py
  - tests/test_counterparty_risk_rule.py
---

# 구현 파이프라인 (PJT2) – D1~D7

## Purpose
- D1~D7을 실제 실행 순서/입출력/임시 테이블/아이템포턴시/폴백 관점으로 정리해 재실행·운영 시 참조한다.

## Behavioral Contract
- 입력: `salesmap_latest.db` 스냅샷(스케줄러가 복사). 출력: offline `report_cache/YYYY-MM-DD.json`, online `report_cache/counterparty-risk/online/YYYY-MM-DD.json`(원자적 저장) + `report_cache/llm/{as_of}/{db_hash}/{mode}/...`(LLM 캐시) + status(mode별).
- 모든 단계는 idempotent; 캐시가 동일(as_of+db_signature+mode)하면 재계산을 스킵한다.
- 실패 시 최근 성공본을 그대로 제공(폴백), LLM 실패는 전체 실패로 처리하지 않는다.

## Invariants (Must Not Break, 단계별)
- **D1 deal_norm (TEMP)**: Convert 제외, amount/date parse, is_nononline/is_online, counterparty_name 정규화, pipeline_bucket(확정/예상) 설정. dq_metrics 수집.
- **D2 org_tier_runtime (TEMP)**: 2025 비온라인 확정액 합 → 티어(S0/P0/P1/P2, 삼성 제외), confirmed_amount_2025_won 포함.
- **D3 counterparty_target_2026 (TEMP)**: 유니버스(2025/2026, 모드별 is_nononline/is_online) × 티어 org → baseline_2025, target_2026, is_unclassified flag.
- **D4 tmp_counterparty_risk_rule (TEMP)**: 2026 coverage(확정/예상, 모드 필터), target join, gap/coverage_ratio/pipeline_zero, risk_level_rule(min_cov/월), rule_trigger.
- **D5 report base JSON**: build_counterparty_risk_report → counterparty base row 정렬 + 요약 + data_quality + meta(db_version hash, as_of, generated_at, mode, report_id).
- **D6 에이전트 체인(LLM/폴백)**: registry→orchestrator→CounterpartyCardAgent(프롬프트/캐시 mode별) 실행 → composer가 blockers/evidence/actions 불변 강제 병합. 규칙 risk_level 우선, LLM 결과는 risk_level_llm/llm_meta. **deal_norm 재조회 금지, base row의 top_deals_2026 재사용(없으면 deal 테이블 fallback)**.
- **D7 스케줄/캐시**: run_daily_counterparty_risk_job_all_modes (report_scheduler) → lock → offline+online 순차 실행 → 스냅샷 → 캐시 존재 시 스킵 → 생성/atomic write → mode별 status 업데이트 → retention.
- **프런트 후처리(모드별 DRI universe 적용)**: org_tables_v2.html에서 백엔드 응답을 DRI 기반으로 재구성한다. 출강은 `target26OfflineIsOverride` 전체(0 포함), 온라인은 `target26OnlineIsOverride` & `target26Online!=0` 전체를 size별 전체 DRI에서 불러와 리포트 rows를 투영·target 덮어쓰기·gap/risk 재계산 후 summary를 다시 계산하고, 없던 키는 synthetic row로 추가한다. 팀→파트 필터도 동일 DRI 전체로 매핑한다.

## Coupling Map
- 파이프라인/임시테이블: `dashboard/server/deal_normalizer.py` (build_deal_norm/org_tier/target/risk_rule/report + orchestrator/composer 호출).
- 에이전트/LLM: `dashboard/server/agents/registry.py`, `agents/core/orchestrator.py`, `agents/counterparty_card/*`, `dashboard/server/counterparty_llm.py`(어댑터).
- 스케줄/락/캐시/상태: `dashboard/server/report_scheduler.py`.
- API: `dashboard/server/org_tables_api.py` (`/api/report/counterparty-risk`, `/recompute`, `/status` mode 지원).
- 프런트: `org_tables_v2.html`(`counterparty-risk-daily`/`counterparty-risk-daily-online` fetch/render).
- 테스트: `tests/test_counterparty_risk_rule.py`(D4), `tests/test_counterparty_target.py`, `tests/test_org_tier.py`, `tests/test_deal_normalizer.py`.

## Edge Cases
- DB 최신 수정이 3분 미만이면 DB_UNSTABLE로 재시도 후 실패 시 status에 FAILED 기록, 캐시 기존본 유지.
- 캐시 쓰기 실패 시 기존 캐시 보존, status에 CACHE_WRITE_FAILED 필요(추가 개선 포인트).
- LLM 캐시 파일이 깨졌거나 prompt_version 변경 시 재생성; 실패 시 폴백 evidence/actions 생성.
- deal_norm TEMP 테이블 스코프: build_counterparty_risk_report 내부 커넥션에서만 사용, LLM은 counterparty row에 포함된 top_deals_2026을 사용해 재조회하지 않음.

## Verification
- 로컬 생성 예시:  
  `python - <<'PY'\nfrom dashboard.server.report_scheduler import run_daily_counterparty_risk_job\nprint(run_daily_counterparty_risk_job(force=True))\nPY`
- 캐시 확인: offline `report_cache/YYYY-MM-DD.json`, online `report_cache/counterparty-risk/online/YYYY-MM-DD.json` meta.as_of/db_signature 존재 여부, llm 캐시 폴더(`report_cache/llm/{as_of}/{db_hash}/{mode}`) 생성 여부.
- 단위테스트: `PYTHONPATH=. python3 -m unittest tests.test_deal_normalizer tests.test_org_tier tests.test_counterparty_target tests.test_counterparty_risk_rule tests.test_counterparty_card_agent_contract`.
- 스냅샷 사용 여부: report_work/salesmap_snapshot_* 존재 확인.

## Refactor-Planning Notes (Facts Only)
- build_counterparty_risk_report가 orchestrator/composer를 호출해 counterparties를 완성하므로 agent/registry 변경 시 이 함수가 SSOT다.
- run_daily_counterparty_risk_job_all_modes는 lock을 한 번 잡은 뒤 모드 루프를 실행하므로 force=True로 모드별 재생성을 강제할 수 있다.
- TEMP 테이블은 커넥션 종료 시 사라지므로 외부 커넥션으로 재사용하려 하면 `no such table: deal_norm` 회귀가 발생할 수 있다.
