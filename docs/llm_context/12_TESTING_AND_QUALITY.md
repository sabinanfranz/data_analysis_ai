---
title: 테스트 & 품질 가이드
last_synced: 2026-01-28
sync_source:
  - tests/test_perf_monthly_contracts.py
  - tests/test_pl_progress_2026.py
  - tests/test_api_counterparty_dri.py
  - tests/test_won_groups_json.py
  - org_tables_v2.html
---

## Purpose
- 주요 기능을 보호하는 테스트 커버리지와 실행 방법을 요약해 리팩토링 시 안전망을 확보한다.

## Behavioral Contract
- 파이썬 단위 테스트는 `python -m unittest discover -s tests` 또는 `PYTHONPATH=. python -m unittest tests/<file>.py`로 실행한다. Node 기반 프런트 테스트는 없음(프런트는 정적 HTML).
- 핵심 테스트 역할:
  - `tests/test_perf_monthly_contracts.py`: `/performance/monthly-amounts/summary|deals` 집계/세그먼트/row 순서/코스 ID fallback 검증.
  - `tests/test_pl_progress_2026.py`: `/performance/pl-progress-2026/summary|deals` Target/Expected 합산, excluded 카운트, 정렬/recognizedAmount 검증.
  - `tests/test_api_counterparty_dri.py`: `/rank/2025-top100-counterparty-dri` 온라인 판정, owners 우선순위, Lost/Convert 제외, 정렬, offset/limit 검증.
  - `tests/test_won_groups_json.py`: won-groups-json 메모/웹폼 정제, compact 변환, schema_version/summary/deal_defaults 검증.
  - 기타: deal-check/StatePath/LLM 등 관련 테스트는 없으나 API/프런트 계약이 해당 테스트에 의해 간접 보호된다.

## Invariants (Must Not Break)
- 테스트는 SQLite 임시 DB를 생성해 함수 단위로 호출하며, DB_PATH를 오염시키지 않는다.
- `test_perf_monthly_contracts`는 세그먼트 row 순서(TOTAL→CONTRACT→CONFIRMED→HIGH)와 24개월 키를 고정적으로 검증한다.
- `test_pl_progress_2026`는 Target 값(예: 2601_T=5.8, 2605_T=12.4)과 excluded 카운트(missing_dates, missing_amount)를 검증한다.
- `test_api_counterparty_dri`는 ONLINE 판정 리스트와 People.owner_json 우선 owners 추출을 전제한다.
- `test_won_groups_json`은 webform id 비노출, 날짜 매핑, cleanText 규칙을 전제로 한다.

## Coupling Map
- 테스트 → 대상 코드:
  - perf/pl: `dashboard/server/database.py` (`get_perf_monthly_amounts_summary/deals`, `get_pl_progress_summary/deals`)
  - DRI: `database.get_rank_2025_top100_counterparty_dri`
  - won JSON: `database.get_won_groups_json`, `json_compact.compact_won_groups_json`
  - 프런트 의존: `org_tables_v2.html`는 위 API 계약을 렌더링/드릴다운에 사용한다.

## Edge Cases & Failure Modes
- 로컬 DB 스키마가 테스트 기대와 다르면(컬럼 누락 등) 테스트가 실패하거나 fallback 경로를 통과해 결과가 달라질 수 있다.
- 환경에 따라 `PYTHONPATH=.` 세팅 없이 실행하면 모듈 import 에러가 날 수 있다.
- Node 기반 프런트 테스트가 없으므로 DOM/CSS 회귀는 수동 확인이 필요하다.

## Verification
- `PYTHONPATH=. python -m unittest tests/test_perf_monthly_contracts.py`가 통과하고 months 24개/row 순서가 유지되는지 확인한다.
- `PYTHONPATH=. python -m unittest tests/test_pl_progress_2026.py` 실행 시 Target/Expected/recognizedAmount/ excluded 카운트 검증이 통과하는지 확인한다.
- `PYTHONPATH=. python -m unittest tests/test_api_counterparty_dri.py`가 ONLINE 판정/owners 우선/정렬/offset/limit 케이스를 통과하는지 확인한다.
- `PYTHONPATH=. python -m unittest tests/test_won_groups_json.py`가 webform 날짜/cleanText/compact 규칙을 통과하는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 프런트 UI/UX, 캐시, 모달 동작을 직접 커버하는 자동화 테스트가 없어 API 계약이 맞더라도 렌더링/DOM 회귀는 놓칠 수 있다.
- 테스트가 모두 임시 SQLite를 사용하므로 실제 대용량/실데이터 성능은 별도 검증이 필요하다.
- 캐시/프로세스 재시작 동작은 테스트에 포함되지 않아 mtime 기반 캐시 갱신 문제를 잡지 못한다.
