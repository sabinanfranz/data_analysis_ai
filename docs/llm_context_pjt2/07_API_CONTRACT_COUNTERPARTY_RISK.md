---
title: API 계약 (PJT2) – /api/report/counterparty-risk
last_synced: 2026-01-06
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/deal_normalizer.py
---

# API 계약 (PJT2) – /api/report/counterparty-risk

## Purpose
- 카운터파티 리스크 리포트 API(리포트 캐시/재생성/상태)의 요청/응답/캐시/폴백 계약을 정의한다.

## Behavioral Contract
- 리포트는 캐시 우선(`report_cache/YYYYMMDD.json`). 요청 date에 해당 캐시가 없으면 생성(force) 후 반환.
- 캐시가 없고 생성 실패 시 최근 성공본으로 폴백(meta.is_stale=true). 최근 성공본도 없으면 500.
- date 파라미터 형식 오류는 400.

## Invariants
- GET `/api/report/counterparty-risk?date=YYYY-MM-DD`
  - date 생략 시 today(서버 로컬, 기본 KST).
  - 응답 JSON 필드(요약):  
    - meta: `as_of`, `db_version`(db mtime iso), `generated_at`; 캐시 생성 시 `db_signature`(mtime-size), `generator_version`, `job_run_id`가 report_scheduler에서 추가됨, fallback 시 `is_stale`/`stale_reason` 가능.
    - summary: tier_groups(S0_P0_P1, P2 target/coverage/gap/coverage_ratio), counts(severe/normal/good/pipeline_zero).
    - data_quality: unknown_year_deals, unknown_amount_deals, uncategorized_counterparties.
    - counterparties: orgId/orgName/counterpartyName/tier/baseline/target/confirmed/expected/coverage/gap/coverage_ratio/pipeline_zero/risk_level_rule/risk_level_llm/top_blockers/evidence_bullets/recommended_actions/flags/counts.
- POST `/api/report/counterparty-risk/recompute?date=YYYY-MM-DD`
  - force=true로 캐시 무시, 새 스냅샷/캐시 생성 시도. 락 충돌 시 SKIPPED_LOCKED.
- GET `/api/report/counterparty-risk/status`
  - status.json 반환: last_success, last_run(result/code/message, counts 예정).

## Coupling Map
- 캐시/락/스냅샷: `dashboard/server/report_scheduler.py` (run_daily_counterparty_risk_job, get_cached_report).
- 리포트 생성: `dashboard/server/deal_normalizer.py` (build_counterparty_risk_report).
- API 라우팅: `dashboard/server/org_tables_api.py`.

## Edge Cases
- DB_UNSTABLE_OR_UPDATING(최근 수정 3분) → 재시도 후 실패 시 status=FAILED, 캐시 불변.
- 캐시 깨짐/없음 + 생성 실패 → 최근 성공본 폴백, 없으면 500.
- date=미래/과거 특별 처리 없음(요청 값 기준 캐시 파일명을 사용).

## Verification
- curl 예시:  
  `curl "http://localhost:8000/api/report/counterparty-risk?date=2026-01-10"`  
  → meta.as_of가 2026-01-10이고 counterparties 배열이 있는지 확인.
- recompute:  
  `curl -X POST "http://localhost:8000/api/report/counterparty-risk/recompute?date=2026-01-10"` → status SUCCESS/FAILED 확인.
- status:  
  `curl "http://localhost:8000/api/report/counterparty-risk/status"` → last_success/last_run 필드 확인.

## Refactor-Planning Notes (Facts Only)
- get_cached_report는 캐시가 없으면 FileNotFoundError를 던지고 API 핸들러가 바로 run_daily_counterparty_risk_job(force=True)를 호출하므로 예외 흐름을 바꾸면 캐시 생성 루프가 깨질 수 있다.
- meta 필드(db_version/db_signature/generator_version/job_run_id/is_stale)는 프런트 표시와 캐시 무효화에 사용되며 status.json도 동일 구조를 기대하므로 필드 변경 시 문서와 프런트를 함께 갱신해야 한다.
- recompute는 force=True라도 파일 락(SKIPPED_LOCKED)으로 종료될 수 있으므로 배치/운영에서 재시도 전략이 필요하며 status.json을 확인해야 한다.
