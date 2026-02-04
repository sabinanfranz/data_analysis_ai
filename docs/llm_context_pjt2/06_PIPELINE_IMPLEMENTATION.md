---
title: 구현 파이프라인 (PJT2) – D1~D7
last_synced: 2026-02-04
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
- 입력: 스냅샷된 `salesmap_latest.db` (`report_work/salesmap_snapshot_{as_of}_*.db`). 출력: offline `report_cache/{as_of}.json`, online `report_cache/counterparty-risk/online/{as_of}.json`(원자적 저장) + `report_cache/llm/{as_of}/{db_hash}/{mode}/...`(LLM 캐시) + status(mode별 `status.json`, `status_online.json`).
- 캐시가 존재하고 meta.as_of가 동일하면 SKIPPED_CACHE로 재계산을 건너뛴다. API는 cache miss 시 force 재생성 후 응답한다.
- 실패 시 status에 FAILED 기록, get_cached_report는 last_success 캐시가 있으면 `meta.is_stale=true`로 폴백한다. LLM 실패는 리포트 생성 실패로 전파되지 않고 폴백 텍스트를 사용한다.

## Invariants
- **D1 deal_norm (TEMP)**: Convert 제외. 과정포맷 3종만 online, 나머지는 is_nononline=1. 금액은 금액→예상 체결액 순 파싱(억/천만/만 단위 지원); 실패/음수/미입력은 0, `amount_parse_failed` 플래그 기록. 날짜는 YYYY-MM-DD 파싱, deal_year는 수강시작일→계약 체결일→수주 예정일 순. counterparty NULL이면 `"미분류(카운터파티 없음)"`, counterparty_key=`orgId||counterparty`. bucket은 status/성사 가능성 기반으로 CONFIRMED_CONTRACT/CONFIRMED_COMMIT/EXPECTED_HIGH 결정.
- **D2 org_tier_runtime (TEMP)**: 비온라인 & deal_year=2025 & bucket 확정 2종만 합산, 삼성전자 문자열 포함 org는 tier=None. 확정액 기준으로 S0/P0/P1/P2 임계값 적용.
- **D3 counterparty_target_2026 (TEMP)**: 모드별(is_nononline/is_online) 2025/2026 등장 카운터파티(티어 org 한정) universe 생성 → baseline_2025 확정액 합산 → multiplier(S0=1.5, P0/P1=1.7, P2=1.5)로 target_2026 계산, baseline=0이면 target=0. is_unclassified_counterparty 플래그 포함.
- **D4 tmp_counterparty_risk_rule (TEMP)**: 모드별 2026 딜 중 status NOT IN(Convert, Lost)만 대상, agg_bucket을 확정/예상/IGNORE로 재분류해 coverage/gap/coverage_ratio/pipeline_zero 계산. 월별 min_cov(severe=50%)로 risk_level_rule/rule_trigger 산출. dq_year_unknown/amount_parse_fail 집계 포함.
- **D5 report base JSON**: top_deals_2026는 동일 커넥션에서 deal_norm을 사용해 모드 필터 + 2026 + status NOT IN(Convert, Lost) + amount desc로 TOP_DEALS_LIMIT까지 채워 deals_top에 넣는다. severity 정렬 후 summary counts/tier_groups/data_quality/meta(db_hash, as_of, generated_at, mode, report_id) 생성.
- **D6 에이전트 체인(LLM/폴백)**: registry→orchestrator→CounterpartyCardAgent v1 실행. LLMConfig.from_env(provider=openai & 키 없으면 비활성) 기준; LLM 미설정 시 fallback_blockers/evidence/actions로 채워 카드 필드를 보존한다. deal_norm을 외부에서 재조회하지 않고 base rows + deals_top을 그대로 사용.
- **D7 스케줄/캐시**: run_daily_counterparty_risk_job(_all_modes)에서 DB 안정창(기본 180s) 확인 후 스냅샷 복사 → 보고서 생성 → `_atomic_write`로 캐시 저장 → status.json 업데이트 → retention에서 status 파일은 보존. file_lock은 POSIX(fcntl)/Windows(msvcrt) 모두 지원.
- **프런트 후처리(DRI universe 투영)**: 백엔드 결과를 org_tables_v2.html에서 offline/online DRI override 맵으로 투영·target 재계산 후 summary 재계산한다(백엔드 파이프라인에는 영향 없음).

## Coupling Map
- 파이프라인/임시테이블: `dashboard/server/deal_normalizer.py` (build_deal_norm/org_tier/target/risk_rule/report + orchestrator/composer 호출).
- 에이전트/LLM: `dashboard/server/agents/registry.py`, `agents/core/orchestrator.py`, `agents/counterparty_card/*`, `dashboard/server/counterparty_llm.py`(어댑터).
- 스케줄/락/캐시/상태: `dashboard/server/report_scheduler.py`.
- API: `dashboard/server/org_tables_api.py` (`/api/report/counterparty-risk`, `/recompute`, `/status` mode 지원).
- 프런트: `org_tables_v2.html`(`counterparty-risk-daily`/`counterparty-risk-daily-online` fetch/render).
- 테스트: `tests/test_counterparty_risk_rule.py`(D4), `tests/test_counterparty_target.py`, `tests/test_org_tier.py`, `tests/test_deal_normalizer.py`.

## Edge Cases
- cache miss 시 API가 `run_daily_counterparty_risk_job(force=True)`로 생성 후 캐시를 반환, 실패하면 last_success 캐시를 `meta.is_stale=true`로 반환.
- DB 최신 mtime이 안정창 이내이면 리트라이 후 FAILED로 기록하고 FileNotFoundError를 올린다(SKIPPED_LOCKED는 별도).
- status.json/status_online.json은 retention 예외로 삭제되지 않는다; 기타 캐시/스냅샷은 기본 14일 뒤 정리.
- LLM 캐시 손상/프롬프트 변경 시 재생성, LLM 미설정이나 호출 실패 시 fallback evidence/actions로 채워 카드 필드를 유지한다.
- deal_norm TEMP 스코프는 build_counterparty_risk_report 내부 커넥션에 한정되어 외부 커넥션이 재사용하면 `no such table: deal_norm`이 발생한다.

## Verification
- `python -m unittest tests/test_counterparty_risk_rule.py`로 D4 계산 검증.
- `python -m unittest tests/test_counterparty_target.py`로 target 계산/티어 임계값 확인.
- `python -m unittest tests/test_deal_normalizer.py`로 deal_norm 파싱/버킷 분류 확인.
- `python -m unittest tests/test_org_tier.py`로 티어 산정 확인.
- 로컬 생성 예시:  
  `python - <<'PY'\nfrom dashboard.server.report_scheduler import run_daily_counterparty_risk_job\nprint(run_daily_counterparty_risk_job(force=True))\nPY`
- 캐시 확인: offline `report_cache/{as_of}.json`, online `report_cache/counterparty-risk/online/{as_of}.json` meta.as_of/db_signature 존재 여부, llm 캐시 폴더(`report_cache/llm/{as_of}/{db_hash}/{mode}`) 생성 여부.
- 단위테스트: `PYTHONPATH=. python3 -m unittest tests.test_deal_normalizer tests.test_org_tier tests.test_counterparty_target tests.test_counterparty_risk_rule tests.test_counterparty_card_agent_contract`.
- 스냅샷 사용 여부: `report_work/salesmap_snapshot_{as_of}_*.db` 생성 확인.

## Refactor-Planning Notes (Facts Only)
- build_counterparty_risk_report가 orchestrator/composer를 호출해 counterparties를 완성하므로 agent/registry 변경 시 이 함수가 SSOT다.
- run_daily_counterparty_risk_job_all_modes는 lock을 한 번 잡은 뒤 모드 루프를 실행하므로 force=True로 모드별 재생성을 강제할 수 있다.
- TEMP 테이블은 커넥션 종료 시 사라지므로 외부 커넥션으로 재사용하려 하면 `no such table: deal_norm` 회귀가 발생할 수 있다.
