---
title: 상위 조직별 JSON 생성 로직 정리
last_synced: 2026-01-06
sync_source:
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - org_tables_v2.html
  - tests/test_won_groups_json.py
---

## Purpose
- 백엔드 `get_won_groups_json`/`compact_won_groups_json`가 생성하는 조직별 JSON과 프런트(`org_tables_v2.html`) 필터링 동작을 코드 기준으로 설명한다.

## Behavioral Contract
- **백엔드 원본 JSON** (`database.get_won_groups_json`):
  - 입력: 조직 ID. DB에 없으면 `{"organization": None, "groups": []}`.
  - 타깃 상위 조직: 2023/2024/2025 Won 딜이 존재하는 upper_org만 그룹 대상에 포함한다.
  - organization 필드: `id/name/size/industry/industry_major/industry_mid` + 조직 메모(memo.organizationId만) 리스트.
  - People: `id/name/upper_org/team_signature→team/title_signature→title/edu_area/webforms/memos`. webforms는 `"제출된 웹폼 목록"`을 `{name,date}`로 변환하며 webform id는 제외, `webform_history`가 없거나 제출이 없으면 `date="날짜 확인 불가"`, 동일 id 다중 제출은 날짜 리스트.
  - Deals: target upper_org에 속한 People의 모든 상태 딜을 포함하며 `id/name/team/owner/status/probability/expected_date/expected_amount/lost_confirmed_at/lost_reason/course_format/category/contract_date/amount/start_date/end_date/net_percent/created_at` + person 정보(id/name/upper_org/team/title/edu_area) + deal memos를 담는다. owner는 dict/name/id 중 하나를 그대로 노출한다.
  - 그룹: `(upper_org, team)`별로 People/Deal을 모아 upper_org→team 순으로 정렬한다.
- **메모 정제** (`database._clean_form_memo`):
  - utm_source 또는 “고객 마케팅 수신 동의”가 없으면 정제 스킵(None 반환). 폼 스타일(`key: value`)만 처리하며 전화/기업규모/업종/채널/동의/utm, ATD/SkyHive/제3자 동의 키는 제거한다.
  - 남은 키가 `고객이름/고객이메일/회사이름/고객담당업무/고객직급/직책`만이면 `""` 반환(메모 제외). 특수 문구 “단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청”이 있으면 `""` 반환.
  - 정제 성공 시 `cleanText` JSON 문자열로 저장, 실패 시 원문 `text`를 그대로 둔다.
- **Compact 변환** (`json_compact.compact_won_groups_json`):
  - schema_version=`won-groups-json/compact-v1`.
  - Deal.people를 `people_id` 참조로 교체하고 누락된 사람은 stub(id/name/upper_org/team/title/edu_area)로 people 배열에 추가한다.
  - Won 딜을 기준으로 group/organization 요약(`won_amount_by_year`, online/offline 분리)을 생성하고 organization.summary에 누적한다.
  - `deal_defaults`는 course_format/category/owner/day1_teams의 80% 이상 반복 값을 추출해 그룹 수준으로 올리고, 개별 딜에서 동일 값은 제거한다.
  - day1_teams는 `team` JSON을 배열로 정규화하며, 날짜 필드는 모두 YYYY-MM-DD로 맞춘다. **현재 구현은 memos/webforms를 compact 결과에 그대로 보존**하며 null/빈 배열·객체만 제거한다.
- **프런트 필터링** (`org_tables_v2.html`):
  - 회사 선택 시 `/orgs/{id}/won-groups-json`을 1회 fetch 후 캐시에 저장한다.
  - 상위 조직 표에서 선택한 upper_org가 없으면 JSON 버튼을 비활성화하고 안내 문구를 표시한다.
  - “전체 JSON”은 원본 그대로, “선택 상위 조직 JSON”은 `filterWonGroupByUpper`로 groups만 upper_org 일치 항목으로 필터링한다(organization 블록은 그대로 유지). compact 버튼은 `/won-groups-json-compact` 응답을 사용한다.

## Invariants (Must Not Break)
- target_uppers는 Won 딜이 있는 upper_org만 포함하며, Won 없는 조직은 groups가 빈 배열이어야 한다.
- groups 정렬은 upper_org asc → team asc 고정이다(`groups_list.sort`).
- webforms는 `{name, date}`만 노출되고 webform id는 절대 포함하지 않는다. `webform_history` 테이블이 없으면 날짜는 비워두지 않고 `"날짜 확인 불가"`로 채운다.
- 폼 메모 정제는 utm_source/“고객 마케팅 수신 동의”가 없으면 skip, 정보 부족/특수 문구면 drop한다. `cleanText==""` 메모는 결과에서 제외해야 한다.
- compact 변환은 Won 딜이 아닌 값은 summary에 반영하지 않는다. deal_defaults는 3건 이상·80% 이상 반복일 때만 설정된다. **memos/webforms는 compact에서도 남으므로 개인정보 제거 용도가 아니다.**
- 프런트 선택 JSON은 organization 블록을 수정하지 않고 groups만 필터링해야 하며, 선택이 없으면 버튼이 비활성화되어야 한다.

## Coupling Map
- 백엔드 생성: `dashboard/server/database.py:get_won_groups_json`, `_clean_form_memo`, `_safe_json_load`.
- Compact 변환: `dashboard/server/json_compact.py:compact_won_groups_json`, `SCHEMA_VERSION`.
- 프런트 처리: `org_tables_v2.html`(`fetchWonGroupsJson`, `filterWonGroupByUpper`, JSON 모달 렌더러).
- 테스트: `tests/test_won_groups_json.py`가 메모/웹폼 정제와 compact summary/기본 필드 존재 여부를 검증한다.

## Edge Cases & Failure Modes
- 요청 org_id가 없으면 `organization: None, groups: []`를 반환한다.
- `webform_history` 테이블이 없는 DB에서는 날짜 매핑을 건너뛰지만 전체 JSON 생성은 계속된다.
- memos에 폼이 아닌 텍스트만 있으면 `cleanText` 없이 `text`를 그대로 둔다.
- compact 변환에서 deal_defaults 추출 조건을 만족하지 못하면 `deal_defaults` 필드가 null/빈 객체로 제거된다.
- 프런트 캐시가 무효화되지 않아 DB 교체 후 새로고침 전까지 이전 JSON이 유지될 수 있다.

## Verification
- 샘플 org_id로 `/api/orgs/{id}/won-groups-json`을 호출해 industry_major/mid, webforms `{name,date}` 매핑, 폼 메모 정제/제외 규칙이 적용됐는지 확인한다.
- 동일 org_id로 `/api/orgs/{id}/won-groups-json-compact`를 호출해 schema_version, organization.summary, deal_defaults가 적용되고 memos/webforms가 원본과 동일하게 남는지 확인한다.
- 프런트에서 상위 조직 미선택 시 JSON 버튼이 비활성화되고, 선택 시 groups가 해당 upper_org만 남는지 DevTools에서 확인한다.
- Won 딜이 없는 조직으로 호출할 때 groups가 빈 배열인지, Won 딜 있는 조직은 groups 정렬이 upper_org→team 순인지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 메모 정제 규칙이 `database._clean_form_memo`에만 정의되어 있어 프런트/compact와 별도 관리된다; 규칙 변경 시 세 곳 모두 영향을 받는다.
- `webform_history` 존재 여부에 따라 날짜 매핑이 달라지므로 schema 호환성을 유지하려면 테이블 생성 여부를 명확히 해야 한다.
- groups 필터링 로직이 프런트에서만 적용되고 백엔드는 전체 JSON만 제공하므로, 상위 조직 단위 캐시/쿼리가 필요해도 현재 구조로는 지원되지 않는다.
