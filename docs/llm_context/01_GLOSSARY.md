---
title: 용어집 (Glossary)
last_synced: 2026-12-11
sync_source:
  - dashboard/server/database.py
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
- 온라인 포맷 리스트: `database.ONLINE_COURSE_FORMATS`와 `statepath_engine.ONLINE_COURSE_FORMATS`는 `구독제(온라인)`, `선택구매(온라인)`, `포팅`만 ONLINE으로 본다.
- 규모 그룹 표준화: `infer_size_group`는 `대기업/중견기업/중소기업/공공기관/대학교/기타/미입력` 외 값을 허용하지 않는다.
- 딜 연도 판정: 연산 대부분이 `"계약 체결일"` 앞 4자리, 없을 때 `"생성 날짜"`로 결정된다.
- DRI/딜체크 팀 매핑은 `org_tables_v2.html`의 `PART_STRUCTURE`와 이름 정규화 규칙(`normalize_owner_name`)에 의존한다.

## Coupling Map
- DB/백엔드: `dashboard/server/database.py` (필드명, 온라인/규모 판정, owner 정규화, won 집계).
- 프런트: `org_tables_v2.html` (normalizeUpperOrg, PART_STRUCTURE, course format 표시/필터).
- 파이프라인: `salesmap_first_page_snapshot.py` (raw 필드 적재, webform_history 후처리).
- 문서: `06_API_CONTRACT_CORE.md`(엔드포인트 필드 스키마), `08_MEMO_WEBFORM_RULES.md`(won-groups JSON 필드/정제).

## Edge Cases & Failure Modes
- owner JSON이 비어 있거나 파싱 실패 시 `"미입력"`으로 처리되어 DRI/owners 리스트가 비어 있을 수 있다.
- upper_org/team 공백은 `"미입력"`으로 정규화되어 필터/그룹에 단일 그룹으로 합쳐질 수 있다.
- 온라인 판정 리스트에 없는 변형 값(예: "포팅/SCORM")은 비온라인으로 처리된다.

## Verification
- `_parse_owner_names_normalized`가 영문 1글자 suffix를 제거하고 trim하는지 확인한다(`database.py`).
- `infer_size_group`가 공공/대학교 키워드, 삼성 등 이름에 따른 그룹을 정확히 반환하는지 샘플 문자열로 검증한다.
- `org_tables_v2.html`의 `COUNTERPARTY_ONLINE_FORMATS`가 백엔드 온라인 리스트와 동일한지 확인한다.
- `/api/orgs/{id}/won-groups-json` 응답에 `industry_major/mid`와 webforms `{name,date}`가 포함되고 webform id가 노출되지 않는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 온라인 판정/규모 그룹/owner 정규화 규칙이 `database.py`와 프런트 JS에 중복되어 있어 변경 시 양쪽을 동기화해야 한다.
- 용어집은 스키마 필드명에 직접 의존하므로 DB 컬럼명이 변경되면 즉시 업데이트가 필요하다.
