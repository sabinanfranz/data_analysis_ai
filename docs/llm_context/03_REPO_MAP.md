---
title: 레포 지도 (기능 ↔ 파일)
last_synced: 2026-12-11
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - org_tables_v2.html
  - salesmap_first_page_snapshot.py
  - build_org_tables.py
  - tests/test_pl_progress_2026.py
---

## Purpose
- 주요 기능이 어느 파일에 구현되어 있는지 빠르게 찾을 수 있도록 경로/책임/테스트 연결을 정리한다.

## Behavioral Contract
- 기능 추가/변경 시 아래 매핑에 따라 백엔드(DB 집계), 라우터, 프런트 렌더러, 테스트, 문서를 함께 업데이트한다.
- 조직/People/Deal 데이터는 SQLite(`salesmap_latest.db`)를 직접 읽으며, 프런트는 정적 HTML(`org_tables_v2.html`)이 `/api/*`를 호출한다.

## Invariants (Must Not Break)
- FastAPI 엔트리: `dashboard/server/main.py`에서 `org_tables_api.py` 라우터를 include해야 한다.
- DB 집계는 `dashboard/server/database.py` 단일 파일에 존재하며, 라우터는 이 모듈 함수를 직접 호출한다.
- 프런트는 `org_tables_v2.html` 단일 파일로 배포되며, API_BASE는 origin+/api 또는 `http://localhost:8000/api`로 계산된다.
- 스냅샷/정적 HTML 생성 스크립트는 각각 `salesmap_first_page_snapshot.py`, `build_org_tables.py`에 고정돼 있다.

## Coupling Map
- 백엔드: `dashboard/server/org_tables_api.py`(라우트) ↔ `dashboard/server/database.py`(집계/정렬/캐시) ↔ SQLite 스냅샷.
- 프런트: `org_tables_v2.html` 렌더러(`renderBizPerfPlProgress2026`, `renderBizPerfMonthly`, `renderRankCounterpartyDriScreen`, `renderDealCheckScreen`, `renderStatePathMenu`, `renderOrgScreen` 등) ↔ `/api/*`.
- 데이터/파이프라인: `salesmap_first_page_snapshot.py`가 DB를 생성/교체, webform_history 후처리.
- 정적 HTML: `build_org_tables.py` → `org_tables.html`(딜 있음/없음 3×3 레이아웃).
- KPI Review Report(오프라인 HTML): `build_kpi_review_report.py`(CLI 생성) ↔ `templates/kpi_review_report.template.html`(UI/스키마) ↔ `data/existing_orgs_2025_eval.txt`(ORG_MAP/필터링 기준).
- 테스트: `tests/test_pl_progress_2026.py`, `tests/test_perf_monthly_contracts.py`, `tests/test_api_counterparty_dri.py`, `tests/test_won_groups_json.py`, `tests/test_deal_check_edu1.py` 등.

## Edge Cases & Failure Modes
- 프런트 캐시(Map)로 인해 DB 교체 후 새로고침을 하지 않으면 오래된 데이터가 남는다.
- 스냅샷 교체 실패 시 `salesmap_first_page_snapshot.py`가 폴백 DB를 남길 수 있어 API가 이전 DB를 계속 읽을 수 있다.
- 일부 테스트는 DB 스키마 열 존재 여부에 따라 fallback 로직을 검증하므로, 컬럼 제거 시 다른 경로가 실행될 수 있다.

## Verification
- `org_tables_api.py`에 `/performance/*`, `/rank/*`, `/statepath/*`, `/deal-check/*`, `/qc/*`, `/orgs/*` 라우트가 모두 선언되고 main.py에서 include되는지 확인한다.
- `database.py`에 PL/월별/DRI/딜체크/Won JSON/StatePath 집계 함수가 존재하고 캐시 키에 DB mtime이 포함되는지 확인한다.
- `org_tables_v2.html`의 MENU_SECTIONS와 render 함수가 라우트와 1:1 매핑되는지, API_BASE 계산이 origin+/api 또는 localhost인지 확인한다.
- `salesmap_first_page_snapshot.py`가 체크포인트/백업/replace_file_with_retry를 수행하고 run_history.jsonl에 기록하는지 실행 로그로 검증한다.
- `build_org_tables.py`를 실행해 org_tables.html이 생성되고 규모/조직/People/Deal/메모 흐름이 동작하는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- DB 집계/라우터/테스트/프런트 렌더러가 동일 기능별로 강하게 결합돼 있어 파일 간 변경 영향 범위가 넓다.
- 캐시 키가 DB mtime 기반인 함수가 많아(DBRANK/PL/Monthly/DRI) 프로세스 재시작 전까지 새 DB가 반영되지 않는다.
- 프런트/정적 HTML/스냅샷 스크립트가 모두 `salesmap_latest.db` 경로를 상수로 사용해 경로 변경 시 다중 수정이 필요하다.
