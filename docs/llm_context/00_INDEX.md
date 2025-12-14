# LLM Context Pack 인덱스

이 패키지는 외부 LLM에게 정확한 프로젝트 컨텍스트를 짧은 시간에 전달하기 위한 문서 모음입니다.  
프로젝트의 핵심 흐름(데이터 수집 → API → 프런트/UX → JSON 가공)을 빠르게 파악하도록 구성했습니다.  
각 문서는 150~350줄 이하로 유지하는 것을 권장하며, 범위(scope)와 마지막 검증 시점(last_verified)을 명시해 신뢰도를 표시합니다.  
질문 유형에 맞는 문서를 바로 찾을 수 있도록 “질문 → 문서” 매핑을 제공합니다.  
scope는 `stable`(구조/원리 고정), `operational`(운영/실행 절차), `ux`(화면 동작/사용 흐름), `reference`(보조/참고)로 구분합니다.  
last_verified는 실제 확인/테스트 시점을 적고, 미검증이면 `TODO`로 남깁니다.

## 질문 유형별 참조 문서
- API 동작/엔드포인트 질문 → `docs/api_behavior.md` (scope: stable, last_verified: 2025-12-22)
- 프런트 UX/조직·People·Deal 화면 + StatePath 24→25 패턴/필터/툴팁 → `docs/org_tables_v2.md` (scope: ux, last_verified: 2025-12-22)
- 백엔드/프런트 계약(엔드포인트/상태/캐시) → `docs/llm_context/06_API_CONTRACT_CORE.md`, `docs/llm_context/09_FRONTEND_ORG_TABLES_V2_CONTRACT.md` (scope: stable/ux, last_verified: 2025-12-22)
- 상위 조직별 JSON 생성·필터/compact 변환(백엔드+프런트) → `docs/json_logic.md` (scope: stable, last_verified: 2025-12-14)
- 스냅샷/데이터 적재 파이프라인(웹폼 수집 포함) → `docs/snapshot_pipeline.md` (scope: operational, last_verified: 2025-12-14)
- 실행/사용 가이드(백엔드 기동, 정적 서버, 드롭다운 동작) → `docs/user_guide.md` (scope: operational, last_verified: 2025-12-15)
- 학습용 개요/읽기 순서/참고 개념 → `docs/study_material.md` (scope: reference, last_verified: 2025-12-10)
- 기타 사용법/HTML 생성 등 세부 가이드 → `docs/org_tables_usage.md` (scope: reference, last_verified: 2025-01-07)

## 업데이트 원칙
- 문서 수정 시 scope와 last_verified를 함께 갱신합니다. 테스트/실행으로 확인했다면 날짜를, 미확인 시 `TODO`를 남깁니다.
- 본 인덱스에 새 문서가 추가되면 “질문 유형별 참조 문서”에 매핑을 추가합니다.
