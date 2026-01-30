---
title: LLM Context Pack (PJT2) 인덱스 – 카운터파티 리스크 리포트
last_synced: 2026-01-29
sync_source:
  - docs/llm_context_pjt2/01_GLOSSARY_llm.md
  - docs/llm_context_pjt2/02_ARCHITECTURE_llm.md
  - docs/llm_context_pjt2/03_REPO_MAP_llm.md
  - docs/llm_context_pjt2/04_DATA_MODEL_COUNTERPARTY.md
  - docs/llm_context_pjt2/05_RULEBOOK_COUNTERPARTY_RISK.md
  - docs/llm_context_pjt2/06_PIPELINE_IMPLEMENTATION.md
  - docs/llm_context_pjt2/07_API_CONTRACT_COUNTERPARTY_RISK.md
  - docs/llm_context_pjt2/08_LLM_INTEGRATION.md
  - docs/llm_context_pjt2/09_RUNBOOK_SCHEDULING_AND_OPS.md
  - docs/llm_context_pjt2/10_TESTING_AND_QA.md
  - docs/llm_context_pjt2/99_OPEN_QUESTIONS.md
---

# LLM Context Pack (PJT2) 인덱스 – 카운터파티 리스크 리포트

## Purpose
- 카운터파티 리스크 리포트(MVP, 31.1~31.7) 전용 컨텍스트 팩이다. salesmap_latest.db만 주어진 외부 LLM/Codex가 규칙/파이프라인/LLM 캐시/스케줄을 빠르게 복원하도록 안내한다.

## 문서 맵 / 읽기 순서
- 01_GLOSSARY_llm: 핵심 용어/키/해시 정의.
- 02_ARCHITECTURE_llm: 스냅샷 DB → 리포트 생성기 → 캐시/LLM/스케줄 전체 흐름(mermaid).
- 03_REPO_MAP_llm: 기능별 실제 파일 경로.
- 04_DATA_MODEL_COUNTERPARTY: counterparty 키/조인/메모 연결/PRAGMA 근거.
- 05_RULEBOOK_COUNTERPARTY_RISK: 포함/제외/비온라인/연도 귀속/target/gap/coverage/risk 룰 SSOT.
- 06_PIPELINE_IMPLEMENTATION: D1~D7 실제 파이프라인(입·출력/임시테이블/아이템포턴시/폴백).
- 07_API_CONTRACT_COUNTERPARTY_RISK: `/api/report/counterparty-risk` 계약/캐시/상태/오류.
- 08_LLM_INTEGRATION: payload, prompt 원문, 캐시 해시, 폴백/키워드, 호출 대상.
- 09_RUNBOOK_SCHEDULING_AND_OPS: 08:00 cron, DB 안정성, 캐시 저장, 상태/로그, 폴백.
- 10_TESTING_AND_QA: 규칙/캐시/API/프런트 스모크 테스트 가이드.
- 99_OPEN_QUESTIONS: 확정 불가 사항/추가 액션.

## Behavioral Contract
- 각 문서는 frontmatter + Purpose/Behavioral Contract/Invariants/Coupling Map/Edge Cases/Verification 섹션을 갖는다.
- 스키마/경로/규칙은 코드/PRAGMA 근거만 사용하며 추정 금지. 확인 불가 시 99_OPEN_QUESTIONS에 남긴다.
- 새로운 문서/변경 시 본 인덱스의 문서 맵/단축 안내를 갱신한다.

## 질문 유형별 단축 안내
- 규칙/수식/정렬 → 05_RULEBOOK_COUNTERPARTY_RISK
- 데이터/조인/컬럼명 → 04_DATA_MODEL_COUNTERPARTY
- 파이프라인/아이템포턴시 → 06_PIPELINE_IMPLEMENTATION
- API/캐시 → 07_API_CONTRACT_COUNTERPARTY_RISK
- LLM 프롬프트/캐시/폴백 → 08_LLM_INTEGRATION
- 운영/스케줄/폴백 → 09_RUNBOOK_SCHEDULING_AND_OPS
- 테스트 → 10_TESTING_AND_QA

## Invariants
- last_synced는 작성일 기준(2026-01-06). sync_source는 실제 근거 파일만 기재한다.
- 입력 DB: `salesmap_latest.db` PRAGMA 기준. TEMP 테이블/뷰는 코드 그대로(deal_norm/org_tier_runtime/counterparty_target_2026/tmp_counterparty_risk_rule).
- 캐시: `report_cache/YYYY-MM-DD.json`, LLM 캐시 `report_cache/llm/{as_of}/{db_hash}/...`, 스냅샷 `report_work/salesmap_snapshot_<as_of>_<HHMMSS>.db`.
- 스케줄러: APScheduler `REPORT_CRON`(기본 0 8 * * *, TZ=Asia/Seoul). `ENABLE_SCHEDULER=0`이면 미기동.
- LLM: env 설정 시 OpenAI 호출, 키 미설정/미지원 시 fallback-only. 프롬프트는 `dashboard/server/prompts/*.txt`, 없으면 기본 상수 사용.

## Coupling Map
- 코드 근거: `dashboard/server/deal_normalizer.py`, `counterparty_llm.py`, `report_scheduler.py`, `org_tables_api.py`, `org_tables_v2.html`.
- DB 근거: `salesmap_latest.db` PRAGMA (deal/people/organization/memo/webform_history).
- 문서 근거: 본 폴더 내 01~10, 기존 실행/아키텍처 문맥은 `docs/llm_context/*` 일부 참고.

## Edge Cases
- LLM 실제 모델 연동은 현재 폴백 기반임을 명시한다(08 문서에서 다룸).
- 스케줄러 스타트 훅/배포 스크립트는 코드에 따라 달라질 수 있으므로 09/99에 확인 포인트를 남긴다.

## Verification
- 모든 하위 문서가 frontmatter와 필수 섹션을 갖추었는지 확인한다.
- 문서에 언급된 파일/컬럼이 실제 레포/PRAGMA에 존재하는지 `rg`, `PRAGMA table_info`, `python -m unittest discover -s tests`로 검증한다.
- 스케줄러/락/캐시 경로는 `dashboard/server/report_scheduler.py`, `dashboard/server/main.py`, `org_tables_v2.html`를 직접 열람해 동기화한다.

## Refactor-Planning Notes (Facts Only)
- 문서 구조 표준(필수 섹션 + frontmatter)은 본 파일에 서술된 대로 이미 모든 PJT2 문서에 적용되어야 하며, 누락 시 리팩토링 이전에 우선 보완해야 한다.
- 카운터파티 리스크 팩은 salesmap_latest.db 스냅샷 의존성이 강하므로 DB 교체/경로 변경 시 02/06/09 문서도 함께 갱신이 필요하다.
- 프롬프트·LLM·스케줄 관련 최신 사실은 08/09에, 규칙 SSOT는 05에 모여 있으므로 중복 서술을 피하고 해당 문서로 링크하는 것이 유지보수에 유리하다.
