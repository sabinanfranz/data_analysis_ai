---
title: Docs Index (문서 맵)
last_synced: 2026-01-06
sync_source:
  - docs/org_tables_v2.md
  - docs/api_behavior.md
  - docs/json_logic.md
  - docs/snapshot_pipeline.md
  - docs/user_guide.md
  - docs/org_tables_usage.md
---

## Purpose
- `docs/` 전체 문서의 위치와 최신 상태를 안내하고, 각 문서가 Refactor-Ready 표준(Purpose/Behavioral Contract/Invariants/Coupling Map/Edge Cases/Verification)을 충족하는지 확인 기준을 제공한다.

## Behavioral Contract
- **문서 맵(1줄 요약)**:
  - `org_tables_v2.md` (E): org_tables_v2 UI/메뉴/사업부 퍼포먼스/DRI/딜체크/StatePath 동작·불변조건.
  - `api_behavior.md` (D): FastAPI `/api/*` 엔드포인트 정렬/필터/캐시/에러 계약.
  - `json_logic.md` (D/E): `/won-groups-json` 생성·정제·compact 변환과 프런트 필터링.
  - `user_guide.md` (B): 로컬 FastAPI/정적 서버 기동, API_BASE, 스냅샷 실행 예시.
  - `snapshot_pipeline.md` (C): `salesmap_first_page_snapshot.py` 실행 흐름, 체크포인트/백업/폴백 계약.
  - `org_tables_usage.md` (E): 정적 `build_org_tables.py` 버전 생성/레이아웃/필터 동작.
  - `error_log.md` (G): 스냅샷 교체/체크포인트 실패 사례와 복구 절차.
  - `daily_progress.md` (G): 일자별 변경 기록(기능 추가/테스트/문서 동기화).
  - `study_material.md` (G): 프로젝트 학습용 가이드(마지막 업데이트 2025-12-24, 리프레시 필요).
  - `llm_context/00_INDEX.md`, `llm_context_pjt2/00_INDEX.md` (A): LLM 컨텍스트 팩 인덱스(세부 문서는 별도 동기화 필요).

## Invariants (Must Not Break)
- 모든 문서는 front matter(`title/last_synced/sync_source`)와 필수 섹션(Purpose/Behavioral Contract/Invariants/Coupling Map/Edge Cases/Verification/Refactor-Planning Notes)을 포함해야 한다.
- 문서의 주장·예시는 실제 코드/테스트/스크립트 경로에 근거해야 하며, 불일치 발견 시 해당 문서에서 즉시 수정한다.
- docs 맵을 수정하면 본 README도 함께 업데이트해 위치/요약/카테고리가 어긋나지 않도록 유지한다.

## Coupling Map
- UI/프런트 계약: `org_tables_v2.md`, `org_tables_usage.md`, 관련 코드는 `org_tables_v2.html`, `build_org_tables.py`.
- API/로직 계약: `api_behavior.md`, `json_logic.md`, 관련 코드는 `dashboard/server/*.py`.
- 파이프라인/운영: `snapshot_pipeline.md`, `error_log.md`, 실행 코드는 `salesmap_first_page_snapshot.py`, 로그는 `logs/*`.
- 보조 자료: `daily_progress.md`, `study_material.md`, `llm_context*/`.

## Edge Cases & Failure Modes
- 일부 하위 폴더 문서(`llm_context/*`, `llm_context_pjt2/*`, `study_material.md`)는 2025-12 시점 이후 동기화되지 않았으므로 최신 코드와 불일치할 수 있다. 리팩토링/테스트 시 교차 검증이 필요하다.
- docs 맵에 없는 신규 문서가 추가되면 인덱스가 뒤떨어질 수 있으므로 README를 우선 업데이트한다.

## Verification
- 아래 문서들이 모두 `Purpose/Behavioral Contract/Invariants/Coupling Map/Edge Cases/Verification/Refactor-Planning Notes` 섹션을 갖추고 최신 `last_synced`/`sync_source`를 포함하는지 확인한다: `org_tables_v2.md`, `api_behavior.md`, `json_logic.md`, `snapshot_pipeline.md`, `user_guide.md`, `org_tables_usage.md`, `error_log.md`, `daily_progress.md`.
- `study_material.md`, `docs/llm_context/*`, `docs/llm_context_pjt2/*`는 업데이트 대기 상태임을 표시했는지, 추후 동기화 필요 여부를 메모했는지 확인한다.
- 주요 UI/API 문서가 실제 코드(`org_tables_v2.html`, `dashboard/server/*`, `salesmap_first_page_snapshot.py`)와 일치하는지 샘플 호출/빌드로 점검한다.

## Refactor-Planning Notes (Facts Only)
- `llm_context/*` 및 `llm_context_pjt2/*` 문서는 2025-12-26 이후 갱신되지 않아 새 UI(2026 P&L, DRI 필터 등)와 불일치할 가능성이 있다.
- `study_material.md`의 last_synced가 2025-12-24로 남아 있어 최신 실행/배포 흐름과 어긋날 수 있다.
- 문서 수가 많아 섹션 누락 여부를 확인하려면 README의 Verification 체크리스트를 자동화하는 스크립트가 없으며, 수동 점검이 필요하다.
