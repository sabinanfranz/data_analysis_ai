---
title: LLM 연동/캐시 (PJT2) – 31.6
last_synced: 2026-02-05
sync_source:
  - dashboard/server/agents/counterparty_card/agent.py
  - dashboard/server/counterparty_llm.py
  - dashboard/server/agents/core/canonicalize.py
  - dashboard/server/markdown_compact.py
  - dashboard/server/agents/target_attainment/agent.py
  - dashboard/server/agents/target_attainment/schema.py
  - dashboard/server/org_tables_api.py
  - org_tables_v2.html
---

# LLM 연동/캐시 (PJT2) – 31.6

## Purpose
- 카운터파티 리스크 카드용 LLM 입력·프롬프트·캐시·폴백 동작을 현재 코드 기준으로 재구현할 수 있게 SSOT를 제공한다.

## Behavioral Contract
- 대상 선택: `risk_level_rule`이 보통/심각인 모든 카운터파티 + 나머지 중 gap 절대값 상위 20개(target>0)만 LLM 후보로 삼는다.
- 출력 스키마는 risk_level/top_blockers/evidence_bullets(3)/recommended_actions(2~3) 4키 JSON이다. 규칙 risk_level_rule이 UI 기본값이며 LLM 결과는 risk_level_llm로 별도 보관된다.
- 캐시 키: canonical payload → llm_input_hash → `report_cache/llm/{as_of}/{db_hash}/{mode}/{org}__{counterparty}.json`. prompt_version(v1) 또는 입력 해시가 다르면 재계산한다.
- LLM 비활성(OPENAI_API_KEY 없음·LLM_PROVIDER≠openai·OpenAI SDK 미설치)이나 호출/파싱 실패 시 fallback_blockers/evidence/actions를 사용한다.
- 실행 흐름: registry → orchestrator → CounterpartyCardAgent → (cache hit 시 즉시 반환) → cache miss 시 OpenAI ChatCompletions 호출 → composer가 결과를 base rows에 병합한다. `counterparty_llm.py`는 호환용 thin 어댑터일 뿐, deal_norm 재조회는 수행하지 않는다.

## Invariants
- LLM env: LLM_PROVIDER(openai만 유효), OPENAI_API_KEY, LLM_MODEL(기본 gpt-4o-mini), LLM_BASE_URL(optional), LLM_TIMEOUT(기본 15s), LLM_MAX_TOKENS(기본 512), LLM_TEMPERATURE(기본 0.2). `LLMConfig.is_enabled`는 provider=="openai" AND api_key 존재일 때만 true.
- payload 해시: canonical_json(payload) → sha256 = llm_input_hash. prompt_version(v1) 불일치 시 캐시 미스.
- 캐시 경로: `report_cache/llm/{as_of}/{db_hash}/{mode}/{org}__{counterparty}.json`; meta.prompt_version·llm_input_hash가 일치하면 재사용한다.
- 폴백: LLM 미설정/호출 실패/repair 실패/스키마 검증 실패 시 fallback_blockers/evidence/actions 생성, risk_level_llm을 규칙값으로 대체한다.
- signals(lost_90d_count/last_contact_date)는 현재 집계되지 않아 0/None placeholder만 채워진다.
- Payload 필드
  - counterparty_key(orgId/orgName/counterpartyName), tier, report_mode
  - risk_rule: rule_risk_level, pipeline_zero, min_cov_current_month, coverage_ratio, gap, target_2026, confirmed_2026, expected_2026
  - signals: last_contact_date=None, lost_90d_count=0, lost_90d_reasons=[]
  - top_deals_2026: base row에 포함된 리스트 사용, 비어 있으면 deal+people 조인으로 2026 딜을 모드 필터링 후 amount desc TOP_DEALS_LIMIT(10) 중 상위 5개만 payload에 사용.
  - memos: org/deal/people 기준 최근 180일, 최대 20건, 중복 제거 후 1000자 트림.
  - data_quality: unknown_year_deals, unknown_amount_deals, unclassified_counterparty_deals.
- Canonicalization: 키 정렬, 문자열 trim+공백 축약+NFC, 숫자 round6, 딜 amount desc·id asc, 메모 date desc; JSON dumps(separators=",", ":") 후 sha256.
- 프롬프트: `dashboard/server/agents/counterparty_card/prompts/{mode}/v1/{system|user|repair}.txt`(주석 `#` 무시, 없으면 빈 문자열). CounterpartyCardAgent.version="v1".
- Blocker 라벨 허용집합: PIPELINE_ZERO/BUDGET/DECISION_MAKER/APPROVAL_DELAY/LOW_PRIORITY/COMPETITOR/FIT_UNCLEAR/NO_RESPONSE/PRICE_TERM/SCHEDULE_RESOURCE. 폴백은 pipeline_zero 우선, regex 점수 상위 3개, 매치 없으면 FIT_UNCLEAR.

### New flags / rollback (target_attainment)
- 입력 SSOT: LLM 컨텍스트로 사용하는 MD는 `dashboard/server/markdown_compact.py:won_groups_compact_to_markdown`(compact-info-md/v1.1) 결과다. 프런트 Daily Report는 `/api/orgs/{orgId}/won-groups-markdown-compact`로 받아 `won_group_markdown`에 담아 /llm/target-attainment에 전달한다. JS 렌더러 `wonGroupsCompactToMarkdown`는 뷰어 UI 전용이다.
- TARGET_ATTAINMENT_CONTEXT_FORMAT: md | json (default md). derived_md 경로가 md일 때 compact JSON을 SSOT 렌더러로 변환한다. 변환 실패 시 json_fallback.
- TARGET_ATTAINMENT_PROMPT_VERSION: v1 | v2 (default v2). v2 프롬프트는 “Context는 compact-info-md/v1.1 markdown”임을 명시한다.
- include_input=1 또는 debug=1 메타 필드: context_format, context_source(request_md|derived_md|json|json_fallback), prompt_version, context_md_chars, context_md_truncated, context_md_head, context_md_hash, fallback_reason. (MD 본문 전체는 응답에 포함하지 않는다.)
- 요청 스키마: won_group_markdown(옵션 문자열) 또는 won_group_json_compact(옵션 dict) 중 하나 필수. 512,000 bytes 초과 시 PAYLOAD_TOO_LARGE.
- 롤백: env로 context_format=json 또는 prompt_version=v1 설정 후 재기동 → 기존 JSON 컨텍스트/프롬프트로 복귀. 프런트 Phase B 문제가 있으면 won_group_markdown 전송을 중단하고 이전 JSON body로 되돌리면 된다.

### 413(PAYLOAD_TOO_LARGE) 대응 가이드 (target_attainment)
- 한도: 512,000 bytes(request body). Markdown이 길 때 413이 발생할 수 있다.
- 축소 방법: `/api/orgs/{id}/won-groups-markdown-compact?upper_org=...&max_deals=120&max_output_chars=80000&deal_memo_limit=10&memo_max_chars=240&redact_phone=1&format=json` 처럼 max_deals/max_output_chars를 낮춰 재생성한다. 프런트 Daily Report는 1회 자동 재시도(200→120 deals, 120k→80k chars).

### 예시 호출
- won-groups-markdown-compact:
  ```
  curl -s "$API_BASE/orgs/ORG123/won-groups-markdown-compact?upper_org=삼성전자&max_deals=200&max_output_chars=120000&format=json"
  ```
- /llm/target-attainment (markdown only):
  ```
  curl -s -X POST "$API_BASE/llm/target-attainment?include_input=1" \
    -H "Content-Type: application/json" \
    -d '{"orgId":"ORG123","orgName":"샘플","upperOrg":"삼성전자","mode":"offline","target_2026":100,"actual_2026":50,"won_group_markdown":"# md..."}'
  ```

### include_input=1 디버그 읽는 법 (target_attainment)
- context_source: request_md(프런트가 서버 MD를 전달), derived_md(서버가 compact→MD 변환), json, json_fallback.
- context_format/prompt_version: 사용된 플래그 확인.
- context_md_chars/context_md_truncated/context_md_head/context_md_hash: 주입된 MD 요약.
- fallback_reason: derived_md 실패 시 원인 문자열(200자 이내).

## Coupling Map
- 구현: `dashboard/server/agents/counterparty_card/*`(payload/hash/fallback/cache), `counterparty_llm.py`(호환 어댑터), `deal_normalizer.py`(orchestrator+composer 병합).
- 룰/정렬: `05_RULEBOOK_COUNTERPARTY_RISK.md` 참조.
- 캐시 루트/DB 해시: `deal_normalizer.build_counterparty_risk_report` (db_hash=mtime sha256 16자, mode 포함).

## Edge Cases
- OPENAI_API_KEY 미설정, LLM_PROVIDER≠openai, OpenAI SDK 미설치 중 하나라도 발생하면 LLM 호출 없이 폴백 결과를 사용한다.
- repair 프롬프트 후에도 JSON 파싱에 실패하거나 스키마 검증에 실패하면 fallback_output으로 대체된다.
- 캐시 파일이 손상되었거나 prompt_version/llm_input_hash가 다르면 새로 생성한다.
- target_2026=0으로 coverage_ratio가 None일 때 evidence는 gap/pipeline_zero를 기준으로 생성된다.

## Verification
- env 미설정 상태에서 리포트 생성 시 fallback evidence/actions가 포함된 JSON이 반환되는지 확인.
- 동일 payload에서 llm_input_hash 일치로 캐시가 재사용되는지 확인.
- prompts 디렉터리(`counterparty_card/prompts/{mode}/v1`)가 로드되고, 파일이 없을 때 빈 문자열로 호출되는지 확인.
- memo나 deal 순서 변경 시 canonical hash가 달라져 캐시 미스가 발생하는지 확인.
- OPENAI_API_KEY 제거 후 report 생성 시 evidence 3개/actions 2~3개가 채워지는지 확인.

## Refactor-Planning Notes (Facts Only)
- signals가 비어 있어도 payload 해시에 포함되므로 추후 신호 집계 추가 시 캐시 키 변화에 주의해야 한다.
- 프롬프트 파일 부재 시 빈 문자열로 호출되므로 배포 시 프롬프트 번들 누락 여부를 캐시 miss로만 확인할 수 있다.
- LLM 비활성 상태도 성공 경로로 처리되므로 “LLM 호출 여부”는 meta.llm_input_hash/logs를 통해서만 알 수 있다.

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
- canonicalize(payload): 키 정렬, 문자열 trim+공백축약+NFC, 숫자 round6, arrays 정렬 고정(deals amount desc/id asc, memos date desc/source/text). JSON dumps(separators=",",":", sort_keys=True, ensure_ascii=False), sha256.
- compute_llm_input_hash(payload) → 캐시 키/검증.

## Env (로컬 실행용)
- `.env` 예시 키(없으면 폴백-only): `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, `LLM_MODEL`(default gpt-4o-mini), `LLM_BASE_URL(optional)`, `LLM_TIMEOUT`(5~60), `LLM_MAX_TOKENS`(128~2048), `LLM_TEMPERATURE`(0~1).
- 프롬프트 교체: `dashboard/server/agents/counterparty_card/prompts/{mode}/v1/*.txt` 수정으로 가능(placeholder/스키마 규약 유지).

## Verification
- env 미설정 상태에서 리포트 생성 시 fallback evidence/actions가 포함된 JSON이 반환되는지 확인.
- 동일 입력 payload에 대해 llm_input_hash와 캐시가 재사용되는지 확인.
- prompts 디렉터리(`counterparty_card/prompts/{mode}/v1`)가 로드 가능하며 파일 없을 때 default_text로 대체되는지 확인.
- 캐시 적중: 동일 payload 입력 시 CounterpartyCardAgent/loader가 llm_input_hash 일치 여부로 캐시 재사용하는지 확인.
- 폴백: LLM 호출 제거 상태에서 report 생성 시 evidence_bullets 3개/actions 2~3개가 채워지는지 확인.
- 해시 안정성: deal/memo 정렬 변경 시 hash가 바뀌는지, 동일 정렬이면 언어/OS 불문 동일 hash인지 확인.

## Refactor-Planning Notes (Facts Only)
- signals가 비어 있어도 payload 해시에 포함되므로 추후 신호 집계 추가 시 캐시 키 변화에 주의해야 한다.
- 프롬프트 파일 부재 시 빈 문자열로 호출되므로 배포 시 프롬프트 번들 누락 여부를 캐시 miss로만 확인할 수 있다.
- LLM 비활성 상태도 성공 경로로 처리되므로 “LLM 호출 여부”는 meta.llm_input_hash/logs를 통해서만 알 수 있다.
