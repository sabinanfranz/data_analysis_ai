---
title: Open Questions / Assumptions (PJT2)
last_synced: 2026-01-10
sync_source:
  - docs/llm_context_pjt2/00_INDEX.md
---

# Open Questions / Assumptions (PJT2)

## Purpose
- 문서화 시점에 확정하지 못한 사항이나 운영/설계 결정이 필요한 항목을 추적한다.

## Items
- status.json 필드 확장: LLM 폴백/캐시 적중률/last_run counts(심각/보통/양호) 기록을 더 세분화할지 검토 필요.
- LLM 실제 모델 연동: env(LLM_PROVIDER/OPENAI_API_KEY) 설정 시 OpenAI 호출 가능. 실 서비스에서 비용/응답 품질/리페어 재시도 로깅을 어떻게 남길지 결정 필요.
- Deals modal 연동(프런트): 카운터파티 리스크 화면의 “딜 보기” 버튼은 아직 백엔드/API 연결이 없는 placeholder. 필요 시 2026 딜 리스트 API 정의/연동 여부 결정 필요.

## Verification
- 위 항목이 해소되면 본 문서를 업데이트하고 인덱스(00_INDEX.md)의 sync_source를 최신화한다.
