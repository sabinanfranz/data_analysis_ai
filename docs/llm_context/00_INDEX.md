---
title: LLM Context Pack 인덱스
last_synced: 2026-01-06
sync_source:
  - docs/api_behavior.md
  - docs/org_tables_v2.md
  - docs/json_logic.md
  - docs/snapshot_pipeline.md
  - docs/user_guide.md
  - docs/org_tables_usage.md
---

## Purpose
- LLM이 프로젝트 구조/계약/운영 흐름을 빠르게 파악할 수 있도록 llm_context/* 문서의 맵과 최신 상태를 제공한다.

## Behavioral Contract
- 이 인덱스는 `docs/`의 주제별 대표 문서를 A~H 카테고리로 나열하며, 각 문서가 Refactor-Ready 섹션을 갖추었는지 확인하기 위한 체크리스트 역할을 한다.
- 최신 스펙/계약은 항상 `docs/api_behavior.md`, `docs/org_tables_v2.md`, `docs/json_logic.md`, `docs/snapshot_pipeline.md`, `docs/org_tables_usage.md`, `docs/user_guide.md`를 우선 참조한다.
- `llm_context_pjt2/*`는 카운터파티 리스크 리포트(PJT2) 전용 컨텍스트 팩으로 별도 관리한다.

## Invariants (Must Not Break)
- front matter에 last_synced/sync_source가 존재해야 하며, 맵에 포함된 문서들은 모두 필수 섹션(Purpose~Verification)을 갖춘 상태여야 한다.
- 문서 카테고리(A~H)와 링크가 실제 파일 경로와 일치해야 한다.
- 최신 변경은 docs 루트 문서들과 동일한 기준 날짜(2026-01-06)를 반영해야 한다.

## Coupling Map
- 코드/문서: `docs/api_behavior.md`(API), `docs/org_tables_v2.md`(프런트/UX), `docs/json_logic.md`(won-groups JSON), `docs/snapshot_pipeline.md`(스냅샷), `docs/user_guide.md`(로컬 실행), `docs/org_tables_usage.md`(정적 HTML).
- 관련 실행/데이터: `dashboard/server/*`(FastAPI/DB), `org_tables_v2.html`(프런트), `salesmap_first_page_snapshot.py`(스냅샷).
- 테스트: `tests/` 폴더 전반(특히 perf/pl/DRI/won JSON 관련 테스트)로 계약을 검증한다.

## Edge Cases & Failure Modes
- 일부 하위 문서(`llm_context/01_GLOSSARY.md`, `llm_context/03_REPO_MAP.md`, `llm_context/04_DATA_MODEL_SQLITE.md` 등)는 2025-12 기준 내용을 포함할 수 있으므로, 최신 코드와 차이가 의심되면 루트 문서의 Verification 절차를 우선 수행한다.
- `llm_context_pjt2/*`는 본 인덱스와 별도로 관리되며, API/프런트 계약이 다르므로 혼용하면 안 된다.

## Verification
- 아래 카테고리 맵이 실제 파일과 일치하는지 확인한다.
  - A. 아키텍처/개요: `02_ARCHITECTURE.md`, `03_REPO_MAP.md`, `04_DATA_MODEL_SQLITE.md`
  - B. 로컬 실행/운영: `11_RUNBOOK_LOCAL_AND_OPS.md`, `13_RAILWAY_AND_CI.md`, `docs/user_guide.md`
  - C. 데이터/스냅샷: `05_SNAPSHOT_PIPELINE_CONTRACT.md`, `docs/snapshot_pipeline.md`
  - D. API 계약: `06_API_CONTRACT_CORE.md`, `07_API_CONTRACT_RANKINGS.md`, `docs/api_behavior.md`
  - E. 프런트 UI/UX: `09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`, `10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md`, `docs/org_tables_v2.md`, `docs/org_tables_usage.md`
  - F. 테스트/품질: `12_TESTING_AND_QUALITY.md`
  - G. 기타: `01_GLOSSARY.md`, `08_MEMO_WEBFORM_RULES.md`, `99_OPEN_QUESTIONS.md`(pjt2)
  - H. 별도 프로젝트: `llm_context_pjt2/*`
- 각 문서가 필수 섹션(Purpose/Behavioral Contract/Invariants/Coupling Map/Edge Cases/Verification/Refactor-Planning Notes)을 포함하는지 spot-check한다.

## Refactor-Planning Notes (Facts Only)
- llm_context 하위 문서 일부는 2025-12 기준 내용을 포함하고 있어 루트 문서 업데이트(2026-01-06)와 어긋날 수 있다; 순차적으로 last_synced를 2026-01-06으로 맞추며 내용 검증이 필요하다.
- 인덱스와 docs/README.md의 문서 맵이 중복되므로, 어느 한쪽만 갱신되면 다른 쪽이 쉽게 뒤처질 수 있다.
