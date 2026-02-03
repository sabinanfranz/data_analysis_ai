---
title: 메모/웹폼 정제 규칙
last_synced: 2026-01-28
sync_source:
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - tests/test_won_groups_json.py
  - org_tables_v2.html
---

## Purpose
- won-groups-json 생성 시 메모/웹폼을 어떻게 정제·매핑하는지 코드 기준으로 명세해 LLM 입력 품질을 보장한다.

## Behavioral Contract
- 폼 메모 정제(`database._clean_form_memo`):
  - 트리거: `utm_source` 또는 “고객 마케팅 수신 동의”가 있을 때만 실행.
  - 처리: 줄 병합 후 `key: value` 형태만 유지, 전화/기업규모/업종/채널/동의/utm, ATD/SkyHive/제3자 동의 키를 제거.
  - 제외: 남은 키가 `고객이름/고객이메일/회사이름/고객담당업무/고객직급/직책`만 있으면 `""` 반환, 특수 문구 “단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청”이 있으면 `""` 반환.
  - 출력: 정제 성공 시 `cleanText` JSON 문자열, 실패/미트리거 시 None → 원문 text 유지.
- 메모 적용:
  - 조직 메모(memo.organizationId only)는 organization.memos 배열에 추가.
  - People/Deal 메모는 각 엔티티의 memos 배열에 추가, `cleanText==""`는 제외.
  - memo에 `htmlBody`가 있을 수 있으며, won-groups-json에서는 그대로 포함되지만 compact에서는 제거된다(아래 참조).
  - memo 정렬/표시를 위해 `created_at_ts` 필드가 추가로 포함될 수 있으며, 원본 `createdAt` 타임스탬프 문자열을 그대로 담는다.
- 웹폼 정제:
  - People.`"제출된 웹폼 목록"`을 `_safe_json_load` 후 `{id,name}` 배열로 변환.
  - webform_history 테이블에서 (peopleId, webFormId)별 제출 날짜를 조회해 `date`에 단일/리스트를 채우고, 없으면 `"날짜 확인 불가"`.
  - won-groups-json 응답에서는 webform id를 노출하지 않는다.
- compact 변환(`json_compact.py`):
  - memos/webforms를 유지하되 `htmlBody`는 전역적으로 제거한다. text가 비었거나 품질이 낮으면 `htmlBody`를 Markdown으로 변환해 memo.text를 보강한다(표/줄바꿈/리스트 구조 유지, 1열→2열 변환 금지).
  - people가 deal.people_id 참조만 남고 누락된 인물은 stub로 people 배열에 추가된다.
- 프런트 렌더:
  - 메모 상세/딜체크 모달은 `htmlBody`가 있으면 sanitizer(화이트리스트)로 안전하게 렌더하고, 없으면 text를 `pre-wrap`으로 표시한다. sanitizer는 DIV/Table/thead/tbody/tr/th/td/caption까지 허용해 블록/표 구조를 유지하고, 링크는 href 검증 + `_blank`/`noopener`를 강제한다.
  - Compact Markdown(v1.1) 렌더러(서버/프런트 공통)는 deal.memos를 `created_at_ts`(없으면 `date`) 내림차순으로 정렬해 최신 10개를 노출하며, 전화번호는 `[phone]`으로 마스킹하고 200~300자(기본 240자)로 truncate한다.
### (흡수) Won JSON/Compact 생성 세부 규칙
- 백엔드 원본 JSON(`get_won_groups_json`): 입력 org가 없으면 `{"organization": null, "groups": []}`. target_uppers는 2023/2024/2025 Won 딜이 있는 upper_org만 포함하며 People/Deal은 `(upper_org, team)`별로 묶어 upper_org asc → team asc 정렬한다. organization 블록에 `industry_major/industry_mid`와 organizationId만 가진 memos를 포함한다.
- People 필드는 `id/name/upper_org/team_signature→team/title_signature→title/edu_area/webforms/memos`를 모두 노출한다. webforms는 `_safe_json_load` 후 `{name,date}`로 변환하며 webform id는 절대 포함하지 않고, `webform_history`가 없거나 제출이 없으면 date=`"날짜 확인 불가"`, 동일 id 다중 제출은 날짜 리스트로 남긴다.
- Deals는 대상 upper_org People의 모든 상태 딜을 포함해 id/name/team/owner/status/probability/expected_date/expected_amount/lost_confirmed_at/lost_reason/course_format/category/contract_date/amount/start_date/end_date/net_percent/created_at + person 필드를 그대로 둔다. owner는 dict/name/id를 가공 없이 노출한다.
- Compact(`compact_won_groups_json`): schema_version=`won-groups-json/compact-v1`, Won 딜을 기준으로 `won_amount_by_year` 요약을 누적하고 deal.people를 people_id 참조로 교체한다. 누락 인물은 stub(id/name/upper_org/team/title/edu_area)로 추가하고 day1_teams를 배열로 정규화한다. `deal_defaults`는 course_format/category/owner/day1_teams의 80% 이상 반복 값을 추출해 그룹 수준으로 올리고 개별 딜에서 동일 값은 제거한다. memos/webforms는 유지하되 `htmlBody`는 제거되고 text가 비어 있고 htmlBody만 있을 때 plain text로 보강한다. null/빈 배열·객체는 제거된다.
### (흡수) 프런트 필터링/렌더 맵
- `org_tables_v2.html`은 회사 선택 시 `/orgs/{id}/won-groups-json`을 1회 fetch 후 캐시한다. 상위 조직을 선택하지 않으면 JSON 버튼이 비활성화되고 안내 문구를 표시하며, 선택 시 `filterWonGroupByUpper`로 groups만 upper_org 일치 항목을 필터링한다(organization 블록은 그대로 유지). compact 버튼은 `/won-groups-json-compact` 응답을 사용하고 `htmlBody` 미포함 여부를 확인한다.

## Invariants (Must Not Break)
- 폼 메모 정제 트리거는 utm_source 또는 “고객 마케팅 수신 동의” 존재 여부에만 의존하며, 다른 문자열로는 정제가 실행되지 않는다.
- 드롭 키/특수 문구/정보 부족 조건을 만족하면 메모는 결과에서 제외된다.
- webform id는 응답에 포함되지 않으며, date는 `"날짜 확인 불가"`/단일/리스트 3형식 중 하나다.
- compact 변환은 memos/webforms를 유지하지만 htmlBody는 제거된다. text 보강은 compact에 한정되며 일반 메모 조회 API는 원본 text/htmlBody를 그대로 노출한다.
### (흡수) 추가 불변조건
- target_uppers는 Won 딜이 있는 upper_org만 포함해야 하며, groups 정렬은 upper_org asc → team asc로 고정된다.
- compact 변환은 Won 딜이 아닌 값은 summary에 반영하지 않고, `deal_defaults`는 3건 이상·80% 이상 반복일 때만 설정된다.

## Coupling Map
 - 백엔드: `dashboard/server/database.py` (`_clean_form_memo`, `get_won_groups_json`), webform 날짜 조회 `_build_history_index`.
 - Compact: `dashboard/server/json_compact.py` (`compact_won_groups_json`, `_normalize_jsonish`, `_normalize_day1_teams`, `_date_only`).
 - 프런트: `org_tables_v2.html` JSON 모달/웹폼 모달(`openWebformModal`, `getWebformsForPerson`)이 웹폼 `{name,date}`를 표시한다.
 - 테스트: `tests/test_won_groups_json.py`가 메모 정제, webform 날짜 매핑, compact summary/deal_defaults를 검증한다.
 - 프런트 won JSON 모달/compact 버튼/필터 로직은 `org_tables_v2.html` 내 JSON 카드 렌더러와 공유하며, 선택이 없을 때 버튼 비활성 로직이 동일하게 적용된다.

## Edge Cases & Failure Modes
 - webform_history 테이블이 없거나 webFormId/peopleId가 비어 있으면 날짜가 매핑되지 않아 `"날짜 확인 불가"`가 반환된다.
 - 폼 형식이 아니거나 트리거가 없으면 정제가 스킵되어 원문 text가 그대로 노출된다.
 - 정제 실패나 정보 부족으로 `cleanText==""`가 되면 해당 메모는 완전히 제외되어 메모 개수가 줄어든다.
 - Won 딜이 없는 조직은 target_uppers가 비어 있고 groups가 빈 배열이어야 하며 organization 블록은 유지돼야 한다.

## Verification
 - `/api/orgs/{id}/won-groups-json` 호출로 webforms `{name,date}`가 id 없이 포함되는지, 폼 메모가 cleanText로 치환되고 드롭 규칙이 적용되는지 샘플 org로 확인한다.
 - webform_history가 없는 DB에서 date가 `"날짜 확인 불가"`로 노출되는지 확인한다.
- `/api/orgs/{id}/won-groups-json-compact`에서 schema_version과 summary/deal_defaults가 존재하고 memos/webforms가 원본과 동일하게 남으며 날짜가 YYYY-MM-DD로 정규화되는지 확인한다.
 - `tests/test_won_groups_json.py`를 실행해 메모/웹폼 정제·compact 규칙이 검증되는지 확인한다.
### (흡수) 추가 검증 포인트
- 회사 선택 후 상위 조직 미선택 시 JSON 버튼이 비활성화되고 안내 문구가 뜨는지, 선택 시 groups가 해당 upper_org만 남는지 DevTools로 확인한다.
- compact 응답에 `schema_version=won-groups-json/compact-v1`, `deal_defaults` 80% 이상 추출 규칙, `htmlBody` 제거가 적용됐는지 확인한다.

## Refactor-Planning Notes (Facts Only)
 - 폼 정제 규칙이 `database.py`에만 정의되어 프런트/compact와 분리되어 있어 변경 시 세 곳 이상을 조정해야 한다.
 - webform 날짜 매핑이 webform_history 테이블 유무에 따라 달라져 스키마 의존성이 있다.
- compact가 memos/webforms를 그대로 유지하므로 LLM 입력을 비식별화하려면 별도 전처리가 필요하다.
 - target_uppers/upper_org 정렬 규칙이 프런트 필터에도 전파되어 있어 로직 변경 시 JSON 모달/필터를 함께 수정해야 한다.
