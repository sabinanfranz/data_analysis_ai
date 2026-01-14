---
title: 메모/웹폼 정제 규칙
last_synced: 2026-12-11
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
- 웹폼 정제:
  - People.`"제출된 웹폼 목록"`을 `_safe_json_load` 후 `{id,name}` 배열로 변환.
  - webform_history 테이블에서 (peopleId, webFormId)별 제출 날짜를 조회해 `date`에 단일/리스트를 채우고, 없으면 `"날짜 확인 불가"`.
  - won-groups-json 응답에서는 webform id를 노출하지 않는다.
- compact 변환(`json_compact.py`):
  - memos/webforms 필드를 **현재 그대로 유지**하며 날짜만 YYYY-MM-DD로 정규화한다.
  - people가 deal.people_id 참조만 남고 누락된 인물은 stub로 people 배열에 추가된다.

## Invariants (Must Not Break)
- 폼 메모 정제 트리거는 utm_source 또는 “고객 마케팅 수신 동의” 존재 여부에만 의존하며, 다른 문자열로는 정제가 실행되지 않는다.
- 드롭 키/특수 문구/정보 부족 조건을 만족하면 메모는 결과에서 제외된다.
- webform id는 응답에 포함되지 않으며, date는 `"날짜 확인 불가"`/단일/리스트 3형식 중 하나다.
- compact 변환은 memos/webforms를 유지하므로 개인정보 제거 용도로 사용할 수 없다.

## Coupling Map
 - 백엔드: `dashboard/server/database.py` (`_clean_form_memo`, `get_won_groups_json`), webform 날짜 조회 `_build_history_index`.
 - Compact: `dashboard/server/json_compact.py` (`compact_won_groups_json`, `_normalize_jsonish`, `_normalize_day1_teams`, `_date_only`).
 - 프런트: `org_tables_v2.html` JSON 모달/웹폼 모달(`openWebformModal`, `getWebformsForPerson`)이 웹폼 `{name,date}`를 표시한다.
 - 테스트: `tests/test_won_groups_json.py`가 메모 정제, webform 날짜 매핑, compact summary/deal_defaults를 검증한다.

## Edge Cases & Failure Modes
 - webform_history 테이블이 없거나 webFormId/peopleId가 비어 있으면 날짜가 매핑되지 않아 `"날짜 확인 불가"`가 반환된다.
 - 폼 형식이 아니거나 트리거가 없으면 정제가 스킵되어 원문 text가 그대로 노출된다.
 - 정제 실패나 정보 부족으로 `cleanText==""`가 되면 해당 메모는 완전히 제외되어 메모 개수가 줄어든다.

## Verification
 - `/api/orgs/{id}/won-groups-json` 호출로 webforms `{name,date}`가 id 없이 포함되는지, 폼 메모가 cleanText로 치환되고 드롭 규칙이 적용되는지 샘플 org로 확인한다.
 - webform_history가 없는 DB에서 date가 `"날짜 확인 불가"`로 노출되는지 확인한다.
- `/api/orgs/{id}/won-groups-json-compact`에서 schema_version과 summary/deal_defaults가 존재하고 memos/webforms가 원본과 동일하게 남으며 날짜가 YYYY-MM-DD로 정규화되는지 확인한다.
 - `tests/test_won_groups_json.py`를 실행해 메모/웹폼 정제·compact 규칙이 검증되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
 - 폼 정제 규칙이 `database.py`에만 정의되어 프런트/compact와 분리되어 있어 변경 시 세 곳 이상을 조정해야 한다.
 - webform 날짜 매핑이 webform_history 테이블 유무에 따라 달라져 스키마 의존성이 있다.
- compact가 memos/webforms를 그대로 유지하므로 LLM 입력을 비식별화하려면 별도 전처리가 필요하다.
