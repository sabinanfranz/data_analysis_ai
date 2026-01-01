---
title: Docs Index
last_synced: 2025-12-25
sync_source:
  - docs/org_tables_v2.md
  - docs/api_behavior.md
  - docs/llm_context/09_FRONTEND_ORG_TABLES_V2_CONTRACT.md
---

# Docs Index (문서 맵)

- `docs/org_tables_v2.md`: org_tables_v2 UI/메뉴/상태/DRI/Target Board/딜체크 4섹션 최신 동작 정리.
- `docs/api_behavior.md`: FastAPI 엔드포인트 행동 요약(랭킹/딜체크/StatePath/카운터파티 상세 등).
- `docs/json_logic.md`: 상위 조직별 JSON 생성/compact 규칙, 메모/웹폼 정제.
- `docs/user_guide.md`: 로컬 실행/PowerShell 한 줄 실행법.
- `docs/snapshot_pipeline.md`: Salesmap 스냅샷/웹폼 적재/체크포인트/백업 계약.
- `docs/daily_progress.md`: 최근 기능/버그 수정 작업 로그.
- `docs/study_material.md`: 프로젝트 개요와 학습 가이드.
- `docs/org_tables_usage.md`: 정적 org_tables.html 생성/사용 가이드.
- `docs/llm_context/`: LLM 컨텍스트 팩(아키텍처/계약/프런트/테스트 등 세부 문서).
- 기타: `docs/error_log.md`(장애 대응), `docs/llm_context/12_TESTING_AND_QUALITY.md`(테스트 가이드).

## Verification
- 상기 문서가 모두 존재하고 frontmatter(`last_synced`, `sync_source`)가 포함되어 있는지 확인한다.
- UI/엔드포인트 스펙 확인 시 `org_tables_v2.html`, `dashboard/server/*`, `tests/*` 코드와 불일치가 없는지 샘플 실행/호출로 점검한다.
