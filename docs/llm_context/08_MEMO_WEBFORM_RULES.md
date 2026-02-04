---
title: 메모/웹폼 정제 규칙
last_synced: 2026-02-04
sync_source:
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - dashboard/server/markdown_compact.py
  - org_tables_v2.html
  - tests/test_won_groups_json.py
---

## Purpose
- won-groups-json/compact/markdown 생성 및 프런트 렌더 시 메모·웹폼이 어떻게 정제·매핑되는지 SSOT로 기록해 LLM/대시보드 품질을 보장한다.

## Behavioral Contract
### 폼 메모 정제 (`database._clean_form_memo`)
- 트리거: memo.text에 `utm_source` **또는** “고객 마케팅 수신 동의” 키가 있을 때만 실행(없으면 원문 그대로).
- 처리: 줄 병합 후 `key: value` 형식만 남기고 전화/기업규모/업종/채널/동의/utm/ATD/SkyHive/제3자 동의 키를 제거.
- 제외: 남은 키가 `{고객이름,고객이메일,회사이름,고객담당업무,고객직급/직책}`만이면 `""` 반환; 특수 문구 “단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청”이 있으면 `""` 반환.
- 출력: 정제 성공 시 `cleanText`(dict), 실패/비트리거 시 None → 원문 text 사용. `cleanText==""`는 완전히 제외된다.

### 메모 적용 위치
- organizationId 전용 메모 → organization.memos
- peopleId/organizationId 메모 → person.memos
- dealId 메모 → deal.memos
- `ownerId`를 `_get_owner_lookup`으로 이름 매핑, `created_at_ts`는 원본 createdAt 그대로 보존. `htmlBody` 컬럼이 존재할 경우 원본 메모 API에는 포함된다.

### 웹폼 매핑
- people."제출된 웹폼 목록" JSON을 `{id,name}` 배열로 변환(id/text 혼재 허용).
- `webform_history`(peopleId, webFormId, createdAt)에서 날짜를 찾아 동일 id에 날짜 리스트를 매핑; 없으면 `"날짜 확인 불가"`. people/webform id 중 하나라도 비면 매핑 건너뜀.
- won-groups-json/compact 응답에서는 webform id를 노출하지 않는다.

### compact / markdown 변환
- `compact_won_groups_json`(schema `won-groups-json/compact-v1`)
  - memos/webforms 유지하되 `htmlBody` 전역 제거.
  - text가 없고 htmlBody만 있을 때 plain text로 보강 후 htmlBody 제거.
  - deal.people → people_id 참조로 단순화, 누락 인물 stub 추가. day1_teams JSON을 배열로 정규화.
  - `deal_defaults`는 course_format/category/owner/day1_teams 값이 3건 이상·≥80% 반복 시 group level로 승격하고 개별 딜에서 제거.
  - Won 요약 `won_amount_by_year`/online/offline 누적 후 organization.summary에 합산.
- `won-groups-markdown-compact`(v1.1)
  - 메모 정렬: `created_at_ts` → `date` 내림차순. 최대 `deal_memo_limit`(기본 10).
  - `memo_max_chars`(기본 240)로 truncate, 전화번호는 `[phone]`으로 마스킹, max_output_chars 기본 200k 초과 시 `(truncated due to size limit)` 추가 후 중단.

### 프런트 렌더 규칙 (org_tables_v2.html)
- JSON 버튼: 회사 미선택 또는 upper_org 미선택 시 비활성화 안내, 선택 시 `/won-groups-json` 캐시 후 upper_org 필터(`filterWonGroupByUpper`).
- 메모 모달: htmlBody가 있으면 whitelist sanitizer(div/table/thead/tbody/tr/th/td/caption, 링크 href 검증+`_blank`/`noopener`)로 렌더, 없으면 text `pre-wrap`.
- webform 모달: `{name,date}`만 표시, date는 문자열 또는 배열 그대로 표시.

## Invariants (Must Not Break)
- 폼 정제 트리거는 utm_source 또는 “고객 마케팅 수신 동의” 존재 여부에만 의존한다.
- webform id는 어떤 응답에도 노출되지 않는다; date는 "날짜 확인 불가"|단일|리스트 중 하나여야 한다.
- compact는 memos/webforms를 유지하지만 htmlBody는 항상 제거한다; text 보강은 compact에 한정.
- target_uppers: Won 딜이 있는 upper_org만 포함, groups 정렬 upper_org ASC → team ASC.
- markdown: 전화번호 항상 `[phone]` 마스킹, deal_memo_limit/memo_max_chars/max_output_chars 기본값을 준수해야 한다.

## Coupling Map
- 백엔드: `database.py` (`_clean_form_memo`, `get_won_groups_json`, `_build_history_index`), `json_compact.py`, `markdown_compact.py`.
- 프런트: `org_tables_v2.html` 메모/웹폼 모달·JSON 버튼 로직.
- 테스트: `tests/test_won_groups_json.py`가 cleanText 드롭/정제, webform 날짜 매핑, compact summary/deal_defaults/markdown 규칙을 검증한다.

## Edge Cases & Failure Modes
- webform_history 테이블이 없거나 peopleId/webFormId 빈값 → date="날짜 확인 불가".
- 폼이 아니거나 트리거 부재 → cleanText 없음, 원문 text 그대로 노출.
- cleanText가 `""` → 메모 항목에서 제외되어 개수가 줄 수 있음.
- compact가 memos/webforms를 유지하므로 개인정보 비식별이 필요하면 별도 후처리가 필요하다.

## Verification
- `curl -s "http://localhost:8000/api/orgs/<org>/won-groups-json" | jq '.groups[0].people[0].webforms, .groups[0].deals[0].memos[0]'` → webform id 미노출, date 매핑/cleanText 적용 확인.
- webform_history 없는 DB로 동일 호출 → date="날짜 확인 불가" 확인.
- `curl -s "http://localhost:8000/api/orgs/<org>/won-groups-json-compact" | jq '.schema_version, .organization.summary, .groups[0].deals[0].memos[0]'` → htmlBody 제거·text 보강·deal_defaults 확인.
- `curl -s "http://localhost:8000/api/orgs/<org>/won-groups-markdown-compact" | head -20` → phone 마스킹, memo_max_chars 적용, truncated 문구(필요 시) 확인.

## Refactor-Planning Notes (Facts Only)
- 폼 정제/compact/markdown 규칙이 분산되어 있어 변경 시 세 모듈을 모두 수정해야 한다.
- webform_history 의존도가 있어 스냅샷 후처리 실패 시 날짜 품질이 떨어진다.
- LLM 비식별 요구 시 compact 이후 별도 필터링/마스킹 모듈이 필요하다.
