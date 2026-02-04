---
title: 용어집 (Glossary)
last_synced: 2026-02-04
sync_source:
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - org_tables_v2.html
  - salesmap_first_page_snapshot.py
  - docs/llm_context/06_API_CONTRACT_CORE.md
  - docs/llm_context/08_MEMO_WEBFORM_RULES.md
---

## Purpose
- 프로젝트 전반에서 반복되는 도메인/필드 용어를 실제 코드/DB 스키마에 맞춰 정규화한다.

## Behavioral Contract
- 용어 정의는 SQLite 스냅샷 스키마(`dashboard/server/database.py`), 프런트 렌더러(`org_tables_v2.html`), 스냅샷 파이프라인(`salesmap_first_page_snapshot.py`)에서 사용되는 명칭과 일치해야 한다.
- 모든 예시는 실제 필드/상수/함수에 존재하는 문자열을 사용한다(예: ONLINE 판정 리스트, SIZE_GROUPS).

## Invariants (Must Not Break)
- 온라인 포맷: `ONLINE_COURSE_FORMATS`(database/statepath_engine/json_compact)와 프런트 `COUNTERPARTY_ONLINE_FORMATS`는 정확히 `{구독제(온라인), 선택구매(온라인), 포팅}`만 ONLINE으로 분류한다.
- 규모 그룹: `SIZE_GROUPS`는 `대기업/중견기업/중소기업/공공기관/대학교/기타/미입력`; 문의 인입 전용 `INQUIRY_SIZE_GROUPS`는 `대기업/중견기업/중소기업/공공기관/대학교/기타/미기재`로 고정된다.
- 딜/계약 연도: won 집계는 `YEARS_FOR_WON={2023,2024,2025}`를 사용하며, 기본은 `"계약 체결일"` 연도로 판단하고 없을 때 `"생성 날짜"`로 대체한다.
- DRI/딜체크 팀·파트: `PART_STRUCTURE` 기준(기업교육 1·2팀 파트/온라인셀, 공공교육팀 전체)과 `normalize_owner_name`(영문 1자 suffix 제거 후 trim)이 일치해야 필터/정렬이 정상 동작한다.

## Coupling Map
- DB/백엔드: `dashboard/server/database.py` (온라인/규모 판정, owner 정규화, won 집계, YEARS_FOR_WON).
- StatePath/집계: `dashboard/server/statepath_engine.py` (ONLINE 판정, rail bucket 계산).
- 프런트: `org_tables_v2.html` (normalizeUpperOrg, PART_STRUCTURE, ONLINE set 공유, 사이즈/코스 필터 라벨).
- 파이프라인: `salesmap_first_page_snapshot.py` (raw 필드 적재, webform_history 후처리).
- 문서: `06_API_CONTRACT_CORE.md`(엔드포인트 필드 스키마), `08_MEMO_WEBFORM_RULES.md`(won-groups JSON 필드/정제).

## Edge Cases & Failure Modes
- owner JSON 공백/파싱 실패 시 `"미입력"`으로 채워져 owners 필터가 비거나 DRI 매칭에서 제외된다.
- upper_org/team 공백은 `"미입력"`으로 정규화되어 모두 단일 그룹에 합쳐진다.
- 온라인 판정 리스트에 없는 변형 값(예: `"포팅/SCORM"`, 공백 포함 표기)은 OFFLINE으로 취급된다.
- owner 이름 끝에 영문 1자가 붙어 있을 경우 `normalize_owner_name`가 마지막 글자를 제거해 매칭하므로 원본 표시와 다를 수 있다.

## Verification
- `_parse_owner_names_normalized`와 `normalize_owner_name`가 영문 1글자 suffix 제거 및 trim을 수행하는지 샘플 이름(`\"홍길동A\"`)으로 확인한다.
- `infer_size_group`/`INQUIRY_SIZE_GROUPS` 결과가 `대기업/중견기업/.../미기재` 외 값을 반환하지 않는지 샘플 조직명/규모 문자열로 검증한다.
- `org_tables_v2.html`의 `COUNTERPARTY_ONLINE_FORMATS`가 `database.ONLINE_COURSE_FORMATS`와 동일한 3종인지 비교한다.
- `/api/orgs/{id}/won-groups-json` 응답에 webforms가 `{name,date}`만 노출되고 id가 숨겨지는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 온라인 판정/규모 그룹/owner 정규화 규칙이 `database.py`와 프런트 JS에 중복되어 있어 변경 시 양쪽을 동기화해야 한다.
- 용어집은 스키마 필드명에 직접 의존하므로 DB 컬럼명이 변경되면 즉시 업데이트가 필요하다.
