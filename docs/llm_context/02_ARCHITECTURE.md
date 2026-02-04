---
title: 아키텍처 개요
last_synced: 2026-02-04
sync_source:
  - salesmap_first_page_snapshot.py
  - dashboard/server/main.py
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - org_tables_v2.html
---

## Purpose
- 스냅샷 → FastAPI → 프런트 → 테스트까지 전반 아키텍처와 책임 분리를 최신 코드 기준으로 요약한다.

## Behavioral Contract
- 데이터 수집: `salesmap_first_page_snapshot.py`가 Salesmap API에서 조직/People/Deal/메모/웹폼 제출을 SQLite(`salesmap_latest.db`)에 적재하고, 완료 후 webform_history를 후처리한다.
- 백엔드: `dashboard/server/main.py`가 FastAPI를 기동해 `/api/*` 라우트를 `org_tables_api.py`에 위임하고, CORS와 `/api/initial-data` 초기 데이터 로드, `/` 정적 파일(`org_tables_v2.html`) 제공을 담당한다. 기동 시 `report_scheduler.start_scheduler()`로 Counterparty Risk/Progress 일일 리포트 스케줄러를 백그라운드에서 시작한다.
- DB/집계: `dashboard/server/database.py`가 모든 조회/집계/정렬을 수행하며, P&L/월별 체결액/StatePath/랭킹/딜체크/QC/DRI 로직과 캐시를 포함한다. JSON compact 변환은 `json_compact.py`, StatePath 계산은 `statepath_engine.py`가 수행한다.
- 프런트: `org_tables_v2.html`이 정적 HTML로 API fetch→렌더/모달/캐시를 담당하며, 사이드바 메뉴로 사업부 퍼포먼스/운영/분석/검수 화면을 전환한다.
- 테스트: `tests/test_perf_monthly_contracts.py`, `tests/test_pl_progress_2026.py`, `tests/test_api_counterparty_dri.py` 등에서 월별/P&L/DRI 계약을 검증한다.

## Invariants (Must Not Break)
- 기본 DB 경로는 모든 컴포넌트에서 `salesmap_latest.db`(또는 `DB_PATH` env)로 통일된다(`start.sh`, `database.py`, 프런트 API_BASE 가정).
- 프런트 캐시는 클라이언트 메모리(Map)에만 존재하고 무효화가 없으므로, DB 교체 시 새로고침이 필수이다(`org_tables_v2.html` fetchJson).
- FastAPI는 무상태이며, 모든 집계/정렬 로직은 `database.py`에 단일 책임으로 모여 있다.
- 스냅샷 교체는 tmp→final 원자 교체(잠금 시 폴백)를 전제로 하며, DB 스키마가 변해도 백엔드는 SQLite를 직접 읽는다.

## Coupling Map
- 데이터/파이프라인: `salesmap_first_page_snapshot.py` → SQLite(`salesmap_latest.db`).
- API: FastAPI(`main.py` → `org_tables_api.py`) → DB 집계(`database.py`, `statepath_engine.py`, `json_compact.py`).
- 프런트: `org_tables_v2.html` fetch → `/api/*` → 렌더/모달, 캐시 공유.
- 테스트: `tests/*`가 DB 집계/정렬/포맷 계약을 검증해 프런트·백엔드 동작을 보호.

## Edge Cases & Failure Modes
- DB 부재/잠금 시 대부분의 API가 500을 반환하고, 스냅샷 교체 실패 시 폴백 DB가 생성된다.
- 프런트 캐시가 남은 상태로 DB가 교체되면 UI는 오래된 데이터를 표시한다(새로고침 필요).
- 스냅샷 스키마 변경(컬럼 추가/누락) 시 `_detect_course_id_column`, `_pick_column` 등 백엔드가 유연하게 대체 컬럼을 선택하지만, 일부 집계는 건너뛸 수 있다.

## Verification
- `uvicorn dashboard.server.main:app --reload` 실행 후 `/api/health`가 ok, `/api/sizes`가 SIZE_GROUPS 순으로 반환되는지 확인한다.
- 스냅샷 실행 후 `salesmap_latest.db`가 생성되고 `/api/orgs`/`/api/performance/*` 호출이 성공하는지 확인한다.
- 프런트(`org_tables_v2.html`)를 열어 사이드바 메뉴 전환, 캐시 동작(fetch 후 재호출 없음), 모달 렌더링이 정상인지 확인한다.
- 주요 테스트(`tests/test_perf_monthly_contracts.py`, `tests/test_pl_progress_2026.py`, `tests/test_api_counterparty_dri.py`)가 통과하는지 실행한다.

## Refactor-Planning Notes (Facts Only)
- 데이터 집계/캐시/정렬 로직이 `database.py` 단일 파일에 집중되어 있어 기능 분리 없이 변경 시 충돌 위험이 크다.
- 프런트는 정적 HTML 단일 파일로 모든 렌더러와 스타일을 포함해 영향 범위가 넓다.
- 스냅샷 스크립트의 체크포인트/교체/백업 로직이 다른 파이프라인에서 재사용되지 않고 단독 구현돼 있다.
