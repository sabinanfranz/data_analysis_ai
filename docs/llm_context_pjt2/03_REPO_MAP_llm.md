---
title: 레포 지도 (PJT2) – 기능 ↔ 파일
last_synced: 2026-02-04
sync_source:
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/org_tables_api.py
  - org_tables_v2.html
  - tests/test_counterparty_risk_rule.py
  - dashboard/server/main.py
  - tests/test_api_target_attainment.py
---

# 레포 지도 (PJT2) – 기능 ↔ 파일

## Purpose
- 카운터파티 리스크 리포트 관련 기능이 어떤 파일에 있는지 빠르게 찾을 수 있게 매핑한다.

## Behavioral Contract
- 실제 존재하는 파일/함수만 기재한다(추정 금지). 새 기능 추가 시 이 지도도 갱신한다.

## Invariants
- 리포트 파이프라인은 `dashboard/server/deal_normalizer.py`에 집중되어 있으며, LLM/스케줄/캐시는 별도 모듈에 분리된다.
- 프런트 엔트리포인트는 단일 HTML(`org_tables_v2.html`)이며, 메뉴/렌더러는 JS 상수와 함수로 정의된다.

## Coupling Map
- **파이프라인/룰**: `dashboard/server/deal_normalizer.py`
  - D1 deal_norm 생성, D2 org_tier, D3 counterparty_target_2026, D4 risk_rule, D5 report JSON(`build_counterparty_risk_report`).
- **LLM 캐시/폴백**: `dashboard/server/counterparty_llm.py`
  - payload 생성, canonical 해시, 폴백 evidence/actions, 파일 캐시(`report_cache/llm/...`).
- **스케줄/캐시/락**: `dashboard/server/report_scheduler.py`
  - cron(08:00 KST) 등록, DB 안정성 체크, 스냅샷 복사, 캐시 atomic write, status/status_online, progress L1(PERF) cron(06:00 기본, ENABLE_PROGRESS_SCHEDULER=1일 때).
- **API 라우터**: `dashboard/server/org_tables_api.py`
  - `/api/report/counterparty-risk`, `/report/counterparty-risk/recompute`, `/report/counterparty-risk/status`, `/api/llm/target-attainment` 등.
- **프런트**: `org_tables_v2.html`
  - 메뉴 `counterparty-risk-daily`(출강), `counterparty-risk-daily-online`(온라인). mode별 DRI override universe(출강=offline override 전체, 온라인=online override&비0)로 리포트 rows를 재구성하고 target을 덮어쓴다. 팀→파트 필터도 DRI 전체 기반.
- **테스트**: `tests/test_counterparty_risk_rule.py`(D4 규칙), `tests/test_counterparty_target.py`, `tests/test_deal_normalizer.py`, `tests/test_org_tier.py`, `tests/test_counterparty_llm.py`, `tests/test_api_target_attainment.py`.

## Edge Cases
- Scheduler start hook는 `dashboard/server/main.py`의 startup 이벤트에 연결되어 있으며, `ENABLE_SCHEDULER=0`이면 start_scheduler가 바로 return 한다.
- LLM 실제 모델 호출은 env(LLM_PROVIDER=openai + OPENAI_API_KEY) 설정 시 활성, 미설정 시 폴백-only.

## Verification
- 각 파일에 존재하는 함수/라우트/메뉴 id가 문서에서 언급된 것과 일치하는지 `rg`/테스트로 확인.
- PR 시 새로운 파일/라우트 추가되면 sync_source에 반영.

## Refactor-Planning Notes (Facts Only)
- 프런트가 단일 HTML 파일로 모든 렌더러/스타일을 포함하고 있어 기능별 분리 시 영향 범위가 큼(org_tables_v2.html).
- 리포트 생성/캐시/스케줄/LLM이 파일별로 분리되어 있으나, 규칙 수정 시 deal_normalizer·counterparty_llm·org_tables_v2 모두 수정 필요.
