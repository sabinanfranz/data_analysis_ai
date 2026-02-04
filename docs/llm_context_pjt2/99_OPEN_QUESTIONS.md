---
title: Open Questions / Assumptions (PJT2)
last_synced: 2026-02-04
sync_source:
  - docs/llm_context_pjt2/00_INDEX_llm.md
---

# Open Questions / Assumptions (PJT2)

## Purpose
- 문서화 시점에 확정하지 못한 사항이나 운영/설계 결정이 필요한 항목을 추적한다.

## Items
- status.json 필드 확장: LLM 폴백/캐시 적중률/last_run counts(심각/보통/양호) 기록을 더 세분화할지 미정.
- LLM 실제 모델 연동: env(LLM_PROVIDER=openai, OPENAI_API_KEY) 설정 시 호출 가능하나 운영 검증/비용/품질 로깅 방식은 미정.
- Windows 파일락(msvcrt) 동작은 코드에 구현되어 있으나 운영 환경에서의 안정성 검증 필요.
- .env 로딩 우선순위: main.py가 load_dotenv 시도, 배포 환경에서 env와 dotenv 충돌 여부 추가 확인 필요.
- target-attainment LLM(신규): 512KB 제한/repair 로직은 구현되었으나 실제 OpenAI 응답 품질/시간 로그 모니터링 체계 미정.
