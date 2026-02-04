---
title: LLM Context Pack 인덱스
last_synced: 2026-02-04
sync_source:
  - docs/llm_context/05_SNAPSHOT_PIPELINE_CONTRACT.md
  - docs/llm_context/06_API_CONTRACT_CORE.md
  - docs/llm_context/07_API_CONTRACT_RANKINGS.md
  - docs/llm_context/08_MEMO_WEBFORM_RULES.md
  - docs/llm_context/09_FRONTEND_ORG_TABLES_V2_CONTRACT.md
  - docs/llm_context/10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md
  - docs/llm_context/11_RUNBOOK_LOCAL_AND_OPS.md
  - docs/llm_context/12_TESTING_AND_QUALITY.md
---

## Purpose
- LLM이 프로젝트 구조/계약/운영 흐름을 빠르게 파악할 수 있도록 llm_context/* 문서의 맵과 최신 상태를 제공한다.

## Behavioral Contract
- 이 인덱스는 llm_context/00~14 SSOT 문서를 A~H 카테고리로 나열하며, 각 문서가 Refactor-Ready 섹션을 갖추었는지 확인하기 위한 체크리스트 역할을 한다.
- 삭제된 루트 문서 내용(api_behavior/org_tables_v2/json_logic/snapshot_pipeline/error_log/user_guide/org_tables_usage/kpi_review_report/study_material/daily_progress)은 모두 00~14 SSOT 세트에 흡수되었으며, 본 세트를 우선 참조한다.
- `llm_context_pjt2/*`는 카운터파티 리스크 리포트(PJT2) 전용 컨텍스트 팩으로 별도 관리하며, 본 세트와 혼용하지 않는다.

### 문서 맵 (00~14, SSOT)
- `00_INDEX.md` — 문서 맵/검증 체크리스트.
- `01_GLOSSARY.md` — 도메인/필드 용어 정규화.
- `02_ARCHITECTURE.md` — 스냅샷→API→프런트 흐름과 책임.
- `03_REPO_MAP.md` — 기능별 파일 경로 매핑.
- `04_DATA_MODEL_SQLITE.md` — SQLite 핵심 필드 사용 방식.
- `05_SNAPSHOT_PIPELINE_CONTRACT.md` — 스냅샷 수집/체크포인트/백업 계약.
- `06_API_CONTRACT_CORE.md` — 핵심 조회/퍼포먼스/StatePath/리스크 API.
- `07_API_CONTRACT_RANKINGS.md` — 랭킹/DRI/이상치/리텐션 API.
- `08_MEMO_WEBFORM_RULES.md` — 메모/웹폼 정제 및 won JSON 계약.
- `09_FRONTEND_ORG_TABLES_V2_CONTRACT.md` — org_tables_v2 UI 상태/렌더/캐시.
- `10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md` — build_org_tables 정적 HTML 계약.
- `11_RUNBOOK_LOCAL_AND_OPS.md` — 로컬 실행/운영 변수/캐시 주의.
- `12_TESTING_AND_QUALITY.md` — 테스트 실행법과 보호 계약.
- `13_RAILWAY_AND_CI.md` — GitHub Actions/Release/Railway 재배포 계약.
- `14_db_table_columns.md` — 현재 salesmap_latest.db 테이블/컬럼 SSOT.

## Invariants (Must Not Break)
- front matter에 last_synced/sync_source가 존재해야 하며, 맵에 포함된 문서들은 모두 필수 섹션(Purpose~Verification)을 갖춘 상태여야 한다.
- 문서 카테고리(A~H)와 링크가 실제 파일 경로와 일치해야 한다(SSOT=00~14).
- 최신 변경은 llm_context 세트의 기준 날짜(2026-01-28)와 동기화되어야 한다.

## Coupling Map
- SSOT 문서: `05_SNAPSHOT_PIPELINE_CONTRACT.md`(스냅샷), `06_API_CONTRACT_CORE.md`/`07_API_CONTRACT_RANKINGS.md`(API), `08_MEMO_WEBFORM_RULES.md`(won-groups JSON 정제), `09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`/`10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md`(프런트), `11_RUNBOOK_LOCAL_AND_OPS.md`(운영), `12_TESTING_AND_QUALITY.md`(품질).
- 관련 실행/데이터: `dashboard/server/*`(FastAPI/DB), `org_tables_v2.html`(프런트), `salesmap_first_page_snapshot.py`(스냅샷).
- 테스트: `tests/` 폴더 전반(특히 perf/pl/DRI/won JSON 관련 테스트)로 계약을 검증한다.

## Edge Cases & Failure Modes
- 일부 하위 문서(`01_GLOSSARY.md`, `03_REPO_MAP.md`, `04_DATA_MODEL_SQLITE.md` 등)는 2025-12 기준 내용을 포함할 수 있으므로, 최신 코드와 차이가 의심되면 SSOT 문서의 Verification 절차를 우선 수행한다.
- `llm_context_pjt2/*`는 본 인덱스와 별도로 관리되며, API/프런트 계약이 다르므로 혼용하면 안 된다.

## Verification
- 아래 카테고리 맵이 실제 파일과 일치하는지 확인한다.
  - A. 아키텍처/개요: `02_ARCHITECTURE.md`, `03_REPO_MAP.md`, `04_DATA_MODEL_SQLITE.md`
  - B. 로컬 실행/운영: `11_RUNBOOK_LOCAL_AND_OPS.md`, `13_RAILWAY_AND_CI.md`
  - C. 데이터/스냅샷: `05_SNAPSHOT_PIPELINE_CONTRACT.md`
  - D. API 계약: `06_API_CONTRACT_CORE.md`, `07_API_CONTRACT_RANKINGS.md`
  - E. 프런트 UI/UX: `09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`, `10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md`
  - F. 테스트/품질: `12_TESTING_AND_QUALITY.md`
  - G. 기타: `01_GLOSSARY.md`, `08_MEMO_WEBFORM_RULES.md`, `99_OPEN_QUESTIONS.md`(pjt2)
  - H. 별도 프로젝트: `llm_context_pjt2/*`
- 각 문서가 필수 섹션(Purpose/Behavioral Contract/Invariants/Coupling Map/Edge Cases/Verification/Refactor-Planning Notes)을 포함하는지 spot-check한다.

### Onboarding / Study Path (흡수)
- 프로젝트 개요: Salesmap API → `salesmap_first_page_snapshot.py` → SQLite(DB) → FastAPI(`/dashboard/server`) → 프런트(`org_tables_v2.html`).
- 폴더 가이드: 스냅샷(`salesmap_first_page_snapshot.py`), 백엔드(`dashboard/server/database.py`, `org_tables_api.py`), 프런트(`org_tables_v2.html`), 문서 세트(00~14), 테스트(`tests/`).
- 먼저 익힐 개념: HTTP 백오프/재시도, FastAPI GET 라우터, SQLite PRAGMA, 프런트 fetch/캐시(Map), 메모/웹폼 정제(utm/동의 키 드롭), pytest 기본, `node --test` 개념.
- 실행 예시: 백엔드 `uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000`; 프런트 `python -m http.server 8001`; 스냅샷 `SALESMAP_TOKEN=... python salesmap_first_page_snapshot.py --db-path salesmap_latest.db`; 웹폼만 `python salesmap_first_page_snapshot.py --webform-only --db-path salesmap_latest.db`.
- 코드 읽기 순서: 06/07/09/05/11/08 SSOT 문서 → `dashboard/server/database.py`(won JSON/webform 정제, 집계) → `org_tables_v2.html`(상태/캐시/JSON 버튼 활성화 조건) → 스냅샷 스크립트(백오프/체크포인트/백업) → 주요 테스트.
- 실습 과제 예시: API 필터 추가 후 프런트 연동, JSON 모달 검색 추가, 스냅샷 옵션(샘플/제한) 추가 등.

### Appendix: Daily Progress Log (흡수)
- 이 로그는 동작 계약이 아닌 변경 이력이며, 상세 계약은 00~14 SSOT 문서를 참조해야 한다.
- **2025-12-11**: org_tables_v2 메뉴 확장 및 상위 조직 JSON UX 개선(단일 카드/모달, 전체 리셋 시 검색·규모 초기화). `/api/rank/2025-deals-people`, `/api/rank/mismatched-deals` 추가. webform submit 수집 도구와 webform_history 후처리 추가. 문서/프런트 테스트 갱신.
- **2025-12-14**: compact JSON 엔드포인트(`/orgs/{id}/won-groups-json-compact`) 추가 및 프런트 버튼 연결; 랭킹 UI에 등급/배수/목표 모달 추가; 메모/웹폼 정제 규칙 확장(“고객 마케팅 수신 동의” 포함, ATD/SkyHive/제3자 동의 드롭). webform_history 적재 시 허용 ID 필터링 추가.
- **2025-12-15**: StatePath 엔진(`statepath_engine.py`)과 `/api/orgs/{id}/statepath` 추가, org_tables_v2에 StatePath 모달 및 owners2025 컬럼 반영. 테스트 추가.
- **2025-12-24**: PowerShell 실행 가이드 업데이트, 스냅샷 rename/체크포인트 폴백 로직 강화(`replace_file_with_retry`, `CheckpointManager.save_table`). 문서(05/11) 최신화.
- **2026-01-06**: 2026 P&L/월별 체결액 화면 고도화(T/E 열, current month 하이라이트, assumption bar, deals 모달), `/performance/*` API 및 테스트 정렬/집계 보강. 2026 카운터파티 DRI 화면/필터 정렬 개선(`renderRankCounterpartyDriScreen`, `/rank/2025-top100-counterparty-dri` 캐시 사용).
- **2026-01-27**: 문의 인입 현황(2026) UX 개편(기업규모 상단 버튼 필터, 과정포맷/카테고리 2단 아코디언, `카테고리` 컬럼이 추가된 공용 딜 모달) 및 online_first 필터를 온라인 3종에만 적용하도록 백엔드 수정. docs/06, 09 동기화.

## Refactor-Planning Notes (Facts Only)
- llm_context 하위 문서 일부는 2025-12 기준 내용을 포함하고 있어 최근 업데이트와 어긋날 수 있으므로 순차적으로 last_synced를 맞추며 내용 검증이 필요하다.
- 인덱스와 docs/README.md의 문서 맵이 중복되므로, 어느 한쪽만 갱신되면 다른 쪽이 쉽게 뒤처질 수 있다.
