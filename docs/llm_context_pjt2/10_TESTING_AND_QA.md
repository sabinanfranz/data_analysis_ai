---
title: 테스트 & QA (PJT2)
last_synced: 2026-01-29
sync_source:
  - tests/test_deal_normalizer.py
  - tests/test_org_tier.py
  - tests/test_counterparty_target.py
  - tests/test_counterparty_risk_rule.py
  - tests/test_counterparty_llm.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/counterparty_llm.py
  - org_tables_v2.html
---

# 테스트 & QA (PJT2)

## Purpose
- 카운터파티 리스크 리포트 규칙/캐시/API/프런트가 의도대로 동작하는지 검증 방법을 정리한다.

## Behavioral Contract
- 규칙 테스트는 Python unittest로 커버하며, 프런트 스모크는 node --test 기반(옵션).
- 동일 payload에서 LLM 캐시가 재사용되는지, memo 변경 시 hash 변경되는지 확인한다.
- API/스케줄러는 캐시/폴백 포함 end-to-end로 검증한다.

## Invariants
- 비온라인 판정: ONLINE 3종만 online; 나머지/NULL은 is_nononline=1.
- deal_year 귀속: course_start_date 우선, 없으면 계약 체결일 → 수주 예정일.
- Convert/Lost 제외: coverage/baseline 집계에서 agg_bucket=IGNORE.
- target/coverage/gap/risk_level_rule 계산은 deal_normalizer.py 규칙과 동일해야 한다 (min_cov/severe_threshold, pipeline_zero 포함).
- 티어/삼성 특례: S0~P2 임계값, 삼성전자 이름 포함 시 target=50억, tier 제외.
- LLM OFF 시 fallback evidence/actions가 생성되어 리포트 JSON이 항상 채워져야 한다.
- cache miss → generate(force) → serve 흐름이 깨지지 않아야 한다 (status 캐시, last_success fallback).
- deal_norm 테이블이 없는 상태로 조회되어 `no such table: deal_norm` 오류가 재발하지 않아야 한다 (pipeline에서 커넥션 스코프 유지).
- 단위 테스트:
  - `tests/test_deal_normalizer.py`: 비온라인 판정, 연도 귀속, Convert 제외, 금액 파싱 규칙.
  - `tests/test_org_tier.py`: 티어 경계, 삼성 제외, 온라인/Convert/2026 제외.
  - `tests/test_counterparty_target.py`: baseline→target 산정, EXPECTED_HIGH 제외, 2026-only counterparty 포함.
  - `tests/test_counterparty_risk_rule.py`: coverage/gap/risk_level_rule(min_cov), pipeline_zero, target=0 처리, 미분류 플래그.
  - `tests/test_counterparty_llm.py`: risk_rule-only 입력에서 폴백 evidence/actions가 채워지고 KeyError 없이 동작하는지.
- LLM 캐시: counterparty_llm.compute_llm_input_hash 기반 파일 캐시(`report_cache/llm/...`).
- 프런트: org_tables_v2.html 메뉴 `counterparty-risk-daily` 렌더/필터/테이블-only 모달 정책 준수.

## Coupling Map
- Python 테스트 실행 진입: `PYTHONPATH=. python3 -m unittest tests.test_deal_normalizer tests.test_org_tier tests.test_counterparty_target tests.test_counterparty_risk_rule`.
- 프런트 스모크(옵션): `node --test tests/org_tables_v2_frontend.test.js` (렌더 기본 함수, 메뉴 체계).
- 리포트 생성 CLI 예시: `python - <<'PY'\nfrom dashboard.server.report_scheduler import run_daily_counterparty_risk_job\nprint(run_daily_counterparty_risk_job(force=True))\nPY`.

## Edge Cases
- 캐시 재사용: 동일 as_of+db_signature에서 recompute 없이 GET 시 SKIPPED_CACHE가 status에 기록되는지 확인.
- LLM 실패/미연동: 리포트가 evidence/actions를 폴백으로 채우는지(빈 리스트 금지).
- API 폴백: 오늘 캐시 없고 생성 실패 시 최근 성공본(meta.is_stale=true) 반환 여부.
- deal_norm TEMP 테이블 스코프: LLM이 별도 커넥션에서 deal_norm을 재조회하지 않아야 하며, 캐시 미존재 → 생성 플로우에서 `no such table: deal_norm`이 재발하지 않아야 함.

## Verification
- `python -m unittest discover -s tests` (전체 테스트).
- `python -m unittest tests/test_counterparty_risk_rule.py` (D4 규칙).
- `python -m unittest tests/test_counterparty_target.py` (target 산정/삼성 특례).
- `python -m unittest tests/test_deal_normalizer.py` (deal_norm 파싱/온라인 분류).
- `python -m unittest tests/test_org_tier.py` (티어 경계).
- `python -m unittest tests/test_counterparty_llm.py` (LLM 폴백/캐시).
- `python -m unittest tests/test_api_target_attainment.py` (LLM API 413/메타).
- 규칙 테스트 모두 통과: `PYTHONPATH=. python3 -m unittest tests.test_deal_normalizer tests.test_org_tier tests.test_counterparty_target tests.test_counterparty_risk_rule`.
- 캐시 해시: memo/딜 내용이 동일하면 llm_input_hash도 동일, memo 1개 바뀌면 hash 변경됨을 확인(counterparty_llm.canonical_json).
- API 스모크: `/api/report/counterparty-risk` 호출이 JSON 반환 + meta/db_version 존재. 재호출 시 캐시 적중 확인.
- 프런트: 메뉴 클릭 시 요약/필터/섹션 테이블이 로드되고 오류/빈 화면 없이 동작하는지 수동 확인.

## Refactor-Planning Notes (Facts Only)
- 테스트들은 salesmap_latest.db 내용에 따라 결과가 달라질 수 있는 통합 성격이 강하며, fixture 격리가 없어서 DB 교체 시 실패할 수 있다.
- 프런트 자동 테스트가 부족해 메뉴/모달/정렬 변경은 수동 확인에 의존한다; 필요 시 node 테스트 추가가 요구된다.
- LLM 테스트는 실제 OpenAI 호출을 사용하지 않고 폴백/해시 경로를 검증하므로 ENV 설정에 따라 분기되는 부분을 모킹 없이 유지한다.

