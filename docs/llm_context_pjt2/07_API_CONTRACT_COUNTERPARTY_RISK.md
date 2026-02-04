---
title: API 계약 (PJT2) – /api/report/counterparty-risk
last_synced: 2026-02-04
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/deal_normalizer.py
  - dashboard/server/report/composer.py
---

# API 계약 (PJT2) – /api/report/counterparty-risk

## Purpose
- 카운터파티 리스크 리포트 API(리포트 캐시/재생성/상태)의 요청/응답/캐시/폴백 계약을 정의한다.

## Behavioral Contract
- 캐시 우선 제공: 요청한 date/mode 캐시가 존재하면 그대로 반환, 없으면 생성(force) 후 반환한다.
- 생성 실패 시 last_success 캐시가 있으면 `meta.is_stale=true`로 폴백, 없으면 500을 반환한다.
- date 형식 오류 또는 mode 값이 허용 집합이 아니면 400을 반환한다.

## Invariants
- GET `/api/report/counterparty-risk?date=YYYY-MM-DD&mode=offline|online`
  - date 생략 시 `date.today().isoformat()`, mode 기본 offline.
  - 캐시가 없으면 `run_daily_counterparty_risk_job(as_of_date=date, force=True, mode=mode)`로 생성 후 캐시를 다시 읽어 응답.
  - 응답 meta: as_of, db_version(db mtime iso), generated_at, mode, report_id; 생성 시 db_signature(mtime-size), generator_version, job_run_id 포함, last_success 폴백 시 `is_stale=true`와 `stale_reason=latest_success_fallback`.
  - summary(tier_groups, counts), data_quality(unknown_year_deals, unknown_amount_deals, uncategorized_counterparties), counterparties(규칙 필드 + LLM 필드 + counts + deals_top + llm_meta).
- POST `/api/report/counterparty-risk/recompute?date&mode`
  - mode 기본 offline. force=True로 새 스냅샷/캐시 생성 시도, 파일 락 충돌 시 `{"result":"SKIPPED_LOCKED"}` 반환.
- GET `/api/report/counterparty-risk/status?mode`
  - mode 생략 시 offline/online status 모두 반환(modes_available 포함), 잘못된 mode는 400.
- 캐시 경로: offline `report_cache/{as_of}.json`, online `report_cache/counterparty-risk/online/{as_of}.json`; status 파일(status.json/status_online.json)은 retention에서 삭제하지 않는다.

## Coupling Map
- 캐시/락/스냅샷: `dashboard/server/report_scheduler.py` (run_daily_counterparty_risk_job/all_modes, get_cached_report).
- 리포트 생성: `dashboard/server/deal_normalizer.py` (build_counterparty_risk_report orchestrator+composer).
- API 라우팅: `dashboard/server/org_tables_api.py`.

## Edge Cases
- last_success가 없고 캐시 생성도 실패하면 500 FileNotFoundError로 응답.
- date 형식 오류 또는 mode 값 오류는 400.
- DB_UNSTABLE_OR_UPDATING(최근 수정 3분) → 재시도 후 실패 시 status=FAILED, 캐시 불변.
- 캐시 깨짐/없음 + 생성 실패 → 최근 성공본 폴백, 없으면 500.
- date=미래/과거에 대한 별도 검증 없음(요청 값 그대로 캐시 경로에 사용).

## Verification
- curl GET /api/report/counterparty-risk → meta.mode=offline 확인.
- curl GET /api/report/counterparty-risk?mode=online → online 캐시/생성 확인.
- curl GET /api/report/counterparty-risk/status → offline/online status.json 구조 확인.
- curl POST /api/report/counterparty-risk/recompute?mode=offline → 캐시 재생성 및 status last_run 갱신 확인.
- 예시: `curl \"http://localhost:8000/api/report/counterparty-risk?date=2026-01-10\"` → meta.as_of=2026-01-10 여부 확인.

## Refactor-Planning Notes (Facts Only)
- get_cached_report는 캐시가 없으면 FileNotFoundError를 던지고 API 핸들러가 바로 run_daily_counterparty_risk_job(force=True)를 호출하므로 예외 흐름을 바꾸면 캐시 생성 루프가 깨질 수 있다.
- meta 필드(db_version/db_signature/generator_version/job_run_id/is_stale)는 프런트 표시와 캐시 무효화에 사용되며 status.json도 동일 구조를 기대하므로 필드 변경 시 문서와 프런트를 함께 갱신해야 한다.
- recompute는 force=True라도 파일 락(SKIPPED_LOCKED)으로 종료될 수 있으므로 배치/운영에서 재시도 전략이 필요하며 status.json을 확인해야 한다.
