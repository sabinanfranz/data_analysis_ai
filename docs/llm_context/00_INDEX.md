---
title: LLM Context Pack 인덱스
last_synced: 2025-12-26
sync_source:
  - docs/api_behavior.md
  - docs/org_tables_v2.md
  - docs/llm_context/06_API_CONTRACT_CORE.md
  - docs/llm_context/09_FRONTEND_ORG_TABLES_V2_CONTRACT.md
  - docs/json_logic.md
  - docs/llm_context/13_RAILWAY_AND_CI.md
---

# LLM Context Pack 인덱스

외부 LLM이 짧은 시간에 프로젝트를 이해하도록 돕는 문서 모음이다. 데이터 수집 → API → 프런트/UX → JSON 가공 → 운영/테스트까지 경로별로 정리되어 있으며, 최신 코드 기준(2025-12-26)으로 모두 동기화되어 있다.

## 문서 맵(카테고리별 1줄 요약)
- **A. 아키텍처/개요**
  - `llm_context/02_ARCHITECTURE.md`: 스냅샷 → FastAPI → 프런트 → 캐시까지 전체 구조.
  - `llm_context/03_REPO_MAP.md`: 주요 파일/디렉터리 위치와 용도.
  - `llm_context/04_DATA_MODEL_SQLITE.md`: SQLite 스키마 핵심 필드(organization/people/deal/memo/webform_history).
- **B. 로컬 실행/운영**
  - `user_guide.md`: PowerShell/WSL에서 백엔드/정적 서버 실행 한 줄 예제.
  - `snapshot_pipeline.md`: 스냅샷 스크립트 실행/백오프/체크포인트/웹폼 후처리.
  - `llm_context/11_RUNBOOK_LOCAL_AND_OPS.md`: 로컬/운영 런북, 캐시/DB 교체 시 유의점.
  - `llm_context/13_RAILWAY_AND_CI.md`: GitHub Actions(일일 스냅샷→릴리스→Railway 재배포)와 컨테이너 엔트리 start.sh 동작 계약.
- **C. 데이터/파이프라인**
  - `snapshot_pipeline.md`, `llm_context/05_SNAPSHOT_PIPELINE_CONTRACT.md`: 수집 흐름, 체크포인트/백업 계약.
  - `llm_context/08_MEMO_WEBFORM_RULES.md`: 메모/웹폼 정제 규칙.
- **D. API 계약**
  - `api_behavior.md`: 주요 엔드포인트 동작, won-groups-json/webform 정제.
  - `llm_context/06_API_CONTRACT_CORE.md`: 핵심 API 테이블(edu1 딜체크 포함) 계약/정렬/포맷.
  - `llm_context/07_API_CONTRACT_RANKINGS.md`: 랭킹/DRI/StatePath 포트폴리오 계약.
- **E. 프런트 UI/UX 스펙**
- `org_tables_v2.md`: 메뉴/UX/캐시/사업부 퍼포먼스(월별 체결액·2026 P&L 진행율매출)/StatePath/교육1팀 딜체크 화면 상세.
- `llm_context/09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`: 프런트 상태/캐시 계약, 월별 체결액/2026 P&L 진행율매출(연간 합계 포함)/edu1 테이블 폭·버튼·링크 규칙.
  - `llm_context/10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md`: 정적 `build_org_tables.py`(org_tables.html) 버전 계약.
- **F. 테스트/품질**
  - `llm_context/12_TESTING_AND_QUALITY.md`: pytest/node --test, DB 스위치 시 검증 포인트.
- **G. 기타**
  - `json_logic.md`: 상위 조직 JSON 생성/compact 변환 규칙.
  - `org_tables_usage.md`: 정적 org_tables.html 사용법.
  - `daily_progress.md`, `error_log.md`, `study_material.md`: 작업 일지/장애 대응/학습 가이드.

## 질문 유형별 단축 안내
- API 동작/엔드포인트 질문 → `docs/api_behavior.md`
- 프런트 UX/조직·People·Deal + StatePath + 교육1팀 딜체크 → `docs/org_tables_v2.md`
- 백엔드/프런트 계약(엔드포인트/상태/캐시) → `docs/llm_context/06_API_CONTRACT_CORE.md`, `docs/llm_context/09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`
- 상위 조직별 JSON 생성·필터/compact 변환 → `docs/json_logic.md`
- 스냅샷/데이터 적재 파이프라인 → `docs/snapshot_pipeline.md`
- 실행/사용 가이드 → `docs/user_guide.md`
- 학습용 개요/읽기 순서 → `docs/study_material.md`
- 정적 HTML 생성/사용 → `docs/org_tables_usage.md`

## 업데이트 원칙
- 모든 문서는 최신 코드 기준으로 작성하며, front matter(`title/last_synced/sync_source`)를 유지한다.
- 새 문서를 추가하거나 내용이 변경되면 이 인덱스의 문서 맵/단축 안내를 함께 갱신한다.

## Verification
- 각 문서 상단에 `last_synced: 2025-12-26`와 `sync_source`가 존재하는지 확인한다.
- `org_tables_v2.html`의 최신 기능(교육1팀 딜체크, nowrap 규칙, 2026 P&L 진행율매출 연간 합계 컬럼)이 `org_tables_v2.md`와 `09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`에 반영됐는지 확인한다.
- API `/api/deal-check/edu1`가 `06_API_CONTRACT_CORE.md`에 명시돼 있고 응답 필드가 일치하는지 확인한다.
- snapshot/웹폼 정제 규칙이 `snapshot_pipeline.md`와 `08_MEMO_WEBFORM_RULES.md`에 동일하게 기술됐는지 확인한다.
