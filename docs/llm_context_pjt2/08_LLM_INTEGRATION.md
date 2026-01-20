---
title: LLM 연동/캐시 (PJT2) – 31.6
last_synced: 2026-01-13
sync_source:
  - dashboard/server/counterparty_llm.py
  - dashboard/server/agents/registry.py
  - dashboard/server/agents/core/orchestrator.py
  - dashboard/server/agents/counterparty_card/*
  - dashboard/server/report/composer.py
  - dashboard/server/deal_normalizer.py
  - docs/llm_context_pjt2/05_RULEBOOK_COUNTERPARTY_RISK.md
---

# LLM 연동/캐시 (PJT2) – 31.6

## Purpose
- 카운터파티 리스크 카드용 LLM 입력/프롬프트/캐시/폴백을 재구현할 수 있게 SSOT(에이전트/캐시/프롬프트/합성 규칙)를 제공한다.

## Behavioral Contract
- 호출 대상: 규칙상 `보통/심각` + gap 절대값 상위 TopK(기본 20, target>0) 카운터파티. `양호`는 기본 생략.
- LLM 출력은 JSON 강제(키 4개: risk_level, top_blockers, evidence_bullets(3), recommended_actions(2~3)). 규칙 risk_level이 UI 우선, 불일치 시 evidence에 규칙 언급 포함.
- 캐시: payload canonical JSON → SHA256(llm_input_hash). prompt_version 불일치 시 무효화. 파일 경로 `report_cache/llm/{as_of}/{db_hash}/{mode}/{org}__{counterparty}.json`.
- 실패/미호출: 폴백(blocker 키워드+숫자 근거)으로 evidence/actions를 채우며 job은 SUCCESS_WITH_FALLBACK 취급.
- 실행 경로: registry(report_id×mode) → orchestrator(순차 실행) → CounterpartyCardAgent(모드 인식) → composer(불변 보강). counterparty_llm.py는 호환용 thin adapter.

## Invariants
- Payload 필드:
  - counterparty_key(orgId/orgName/counterpartyName), tier, **report_mode**
  - risk_rule: rule_risk_level, pipeline_zero, min_cov_current_month, coverage, gap, target_2026, confirmed_2026, expected_2026 (coverage/min_cov는 round6)
  - signals: last_contact_date, lost_90d_count, lost_90d_reasons (현재 미집계)
  - top_deals_2026: 금액 기준 desc 상위 5(최대 10). **출처: D5 report row에 포함된 리스트**(deal_norm 재조회 없음, 없으면 deal 테이블 fallback 허용). 필드: id/name/status/possibility/amount/start/end/contract/expected_close/course_id_exists.
  - memos: 최근 180일, 최대 20개, org/deal/people 합집합, dedupe, trim 1000자.
  - data_quality: unknown_year_deals, unknown_amount_deals, unclassified_counterparty_deals.
- Canonicalization: 키 정렬, 문자열 trim+공백 축약+NFC, 숫자 round6, arrays 정렬 고정(딜 amount desc, memos date desc). JSON dumps separators(",",":") → sha256.
- 프롬프트: `dashboard/server/agents/counterparty_card/prompts/{mode}/{version}/{system|user|repair}.txt`(주석 `#` 무시, 없으면 빈 문자열). version 기본 v1.
- Prompt 버전/모델: CounterpartyCardAgent.version="v1". LLM env로 모델/키를 설정, 미설정 시 폴백-only.
- Blocker 라벨 10개만 허용: PIPELINE_ZERO/BUDGET/DECISION_MAKER/APPROVAL_DELAY/LOW_PRIORITY/COMPETITOR/FIT_UNCLEAR/NO_RESPONSE/PRICE_TERM/SCHEDULE_RESOURCE.
- 폴백 blocker: pipeline_zero 우선, 아니면 키워드 regex 매치(top 3) 없으면 FIT_UNCLEAR. 폴백 evidence 3개(숫자+coverage or gap+파이프라인 품질), actions 2~3개(블로커 템플릿).

## Coupling Map
- 구현: `dashboard/server/agents/counterparty_card/*`(payload/hash/fallback/cache), `counterparty_llm.py`(어댑터), `deal_normalizer.py`(orchestrator+composer 병합).
- 룰 참조: `05_RULEBOOK_COUNTERPARTY_RISK.md` for gap/coverage/risk.
- 캐시 경로/DB 해시: `deal_normalizer.build_counterparty_risk_report` (db_hash=mtime sha256 16자, 캐시에 mode 포함).

## Edge Cases
- LLM 미연동 상태: CounterpartyCardAgent 폴백만 반환. 모델 연결 시 해당 호출 사용.
- 캐시 파일 깨짐/해시 불일치: 캐시 미스 후 재생성.
- coverage_ratio None(target=0) → evidence는 gap/pipeline 중심, coverage 기반 근거 금지.

## Verification
- 동일 payload 두 번 호출 시 llm cache hit(파일 존재, llm_input_hash 동일)로 재호출 0회.
- memo 1개 변경 시 llm_input_hash가 달라져 캐시 미스 발생.
- 폴백 동작: LLM 호출을 강제 실패시켜도 evidence 3개/actions 2~3개가 채워지는지 확인(CounterpartyCardAgent).

## System Prompt (v1)
```
너는 B2B 세일즈 리스크 리포트 작성자이자 “근거/액션/블로커 생성기”다.

입력으로 1개 카운터파티에 대한 구조화 JSON(payload)이 주어진다.
너의 임무는 그 입력 JSON에 포함된 사실만 근거로, 지정된 스키마의 “순수 JSON”을 출력하는 것이다.

[절대 금지]
- 확률/성사율/매출/예측(미래 성과 추정) 금지
- 입력 JSON에 없는 사실을 만들어내는 행위(환각) 금지
- 외부 지식/추측/일반론으로 특정 사실을 단정 금지
- 메모 문장을 따옴표로 직접 인용 금지(요약만 가능)

[출력 형식 강제]
- 출력은 반드시 유효한 JSON 1개 객체만 허용한다. (설명 텍스트, 마크다운, 코드블록 금지)
- 출력 키는 정확히 다음 4개만 허용한다:
  1) risk_level
  2) top_blockers
  3) evidence_bullets
  4) recommended_actions
- risk_level 값은 반드시 다음 중 하나: "양호" | "보통" | "심각"
- top_blockers는 길이 0~3의 배열이며, 각 원소는 반드시 아래 10개 라벨 중 하나만 가능:
  "PIPELINE_ZERO" | "BUDGET" | "DECISION_MAKER" | "APPROVAL_DELAY" | "LOW_PRIORITY"
  | "COMPETITOR" | "FIT_UNCLEAR" | "NO_RESPONSE" | "PRICE_TERM" | "SCHEDULE_RESOURCE"
- evidence_bullets는 문자열 배열이며 길이가 정확히 3이어야 한다.
  각 bullet은 한국어 1문장이어야 하며, 최소 1개 bullet에는 입력 JSON의 수치(예: target_2026, confirmed_2026, expected_2026, gap, coverage, lost_90d_count, amount, 날짜 등)가 포함되어야 한다.
- recommended_actions는 문자열 배열이며 길이가 2~3이어야 한다.
  각 action은 한국어 1문장(명령형/행동형)이어야 하며, top_blockers와 논리적으로 정합적이어야 한다.

[중요 규칙]
- 입력 JSON의 risk_rule.rule_risk_level(규칙 결과)은 UI에서 우선 사용된다.
  가능하면 너의 risk_level도 rule_risk_level과 일치시키되,
  만약 다르게 출력한다면 evidence_bullets 중 1개에 “규칙상 리스크는 X로 분류됨”을 반드시 포함하라.
- coverage가 null 또는 "N/A"인 경우, coverage를 근거로 사용하지 말고 gap/pipeline/signal/memo 중심으로 근거를 제시하라.
- 정보가 부족하면 “부족하다”는 점 자체를 데이터 품질/연락/딜 상태 등의 형태로만 표현하고, 새로운 사실을 만들지 마라.
```

## User Prompt 템플릿 (v1)
```
아래는 1개 카운터파티의 입력 payload(JSON)이다. 이 JSON에 없는 사실을 절대 만들지 말고, 오직 아래 출력 스키마에 맞는 “순수 JSON”만 출력하라.

[입력 payload]
{{PAYLOAD_JSON}}

[출력 스키마(키 고정)]
{
  "risk_level": "양호|보통|심각",
  "top_blockers": ["PIPELINE_ZERO|BUDGET|DECISION_MAKER|APPROVAL_DELAY|LOW_PRIORITY|COMPETITOR|FIT_UNCLEAR|NO_RESPONSE|PRICE_TERM|SCHEDULE_RESOURCE"],
  "evidence_bullets": ["...", "...", "..."],
  "recommended_actions": ["...", "..."]
}

[생성 규칙]
- evidence_bullets는 정확히 3개, 각 1문장. 최소 1개는 수치 근거를 포함하라.
- 가능하면 evidence_bullets 중 1개는 memos/signals(lost_90d, last_contact_date)을 요약해 반영하라(직접 인용 금지).
- recommended_actions는 2~3개, 각 1문장(명령형/행동형).
- top_blockers는 최대 3개. 반드시 10개 라벨 중에서만 선택.
- action은 blocker에 정합적으로 매핑하라(아래 힌트 참고).

[blocker → action 힌트(요약)]
- PIPELINE_ZERO: 의사결정자 맵핑 / 니즈 재발굴 / 시퀀스·세미나로 접점 생성
- BUDGET: 예산 라인 확인 / ROI·성과사례 / 단계형 제안
- DECISION_MAKER: 조직도·스폰서 재확인 / 챔피언 대체군
- APPROVAL_DELAY: 구매·법무 체크리스트 / 마감 타임라인 합의
- LOW_PRIORITY: 교육-임원아젠다 연결 재정의 / 타이밍 설계
- COMPETITOR: 비교표+레퍼런스 / 차별 포인트 1페이지
- FIT_UNCLEAR: 니즈 인터뷰 / 맞춤 커리큘럼 / 파일럿
- NO_RESPONSE: 관계 리셋 / 다른 접점 / 내부 소개 루트
- PRICE_TERM: 패키징 조정 / 옵션 분리 / 조건 재설계
- SCHEDULE_RESOURCE: 일정 후보 3개 / 운영 리소스 선점
```

## Repair Prompt (파싱 실패 리트라이)
```
너의 이전 출력은 유효한 JSON이 아니거나 스키마를 위반했다.
설명/마크다운/코드블록 없이, 오직 스키마에 맞는 “순수 JSON 1개 객체”만 다시 출력하라.
허용 키는 risk_level, top_blockers, evidence_bullets, recommended_actions 4개뿐이다.
```

## 폴백 키워드 매칭(요약)
- pipeline_zero==True → ["PIPELINE_ZERO"] 우선.
- regex 매칭(한국어/영문 혼용): BUDGET/APPROVAL_DELAY/DECISION_MAKER/COMPETITOR/NO_RESPONSE/PRICE_TERM/SCHEDULE_RESOURCE/LOW_PRIORITY/FIT_UNCLEAR.
- 점수 높은 순, 동점은 우선순위(APPROVAL_DELAY>DECISION_MAKER>...>FIT_UNCLEAR)로 정렬, 최대 3개. 매치 없으면 ["FIT_UNCLEAR"].
- 폴백 evidence: target/확정/예상/gap, coverage vs min_cov(가능 시), pipeline_zero 메시지.
- 폴백 actions: blocker 매핑 템플릿 상위 2~3개.

## Canonical Hash (요약)
- canonicalize(payload): 키 정렬, 문자열 trim+공백축약+NFC, 숫자 round6, arrays 정렬 고정(deals amount desc/id asc, memos date desc/source/text). JSON dumps(separators:",",":", sort_keys=True, ensure_ascii=False), sha256.
- compute_llm_input_hash(payload) → 캐시 키/검증.

## Env (로컬 실행용)
- `.env` 예시 키(없으면 폴백-only): `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, `LLM_MODEL`(default gpt-4o-mini), `LLM_BASE_URL(optional)`, `LLM_TIMEOUT`(5~60), `LLM_MAX_TOKENS`(128~2048), `LLM_TEMPERATURE`(0~1).
- 프롬프트 교체: `dashboard/server/agents/counterparty_card/prompts/{mode}/v1/*.txt` 수정으로 가능(placeholder/스키마 규약 유지).

## Verification
- 캐시 적중: 동일 payload 입력 시 CounterpartyCardAgent/loader가 llm_input_hash 일치 여부로 캐시 재사용하는지 확인.
- 폴백: LLM 호출 제거 상태에서 report 생성 시 evidence_bullets 3개/actions 2~3개가 채워지는지 확인.
- 해시 안정성: deal/memo 정렬 변경 시 hash가 바뀌는지, 동일 정렬이면 언어/OS 불문 동일 hash인지 확인.

## Refactor-Planning Notes (Facts Only)
- top_deals_2026와 memos 입력이 비어도 폴백 근거/액션은 생성되지만, signals는 현재 집계되지 않아 payload 변경 시 캐시 해시가 달라질 수 있다.
- 프롬프트 파일이 없으면 빈 문자열로 호출되므로 프롬프트만 교체하려면 `dashboard/server/agents/counterparty_card/prompts/{mode}/v1/*.txt` 배포가 필요하다.
- LLM_PROVIDER가 openai가 아니거나 키가 없으면 항상 폴백-only로 동작하므로 배포 환경에서 키 로딩 실패가 곧바로 리포트 실패로 이어지지 않도록 설계되어 있다.
