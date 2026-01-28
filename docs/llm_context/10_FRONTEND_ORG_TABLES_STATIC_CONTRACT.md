---
title: 정적 org_tables.html 프런트 계약
last_synced: 2026-01-28
sync_source:
  - build_org_tables.py
  - org_tables.html
  - tests/test_build_org_tables.py
absorbed_from:
  - org_tables_usage.md
---

## Purpose
- `build_org_tables.py`가 생성하는 정적 HTML(org_tables.html) 버전의 UI/데이터 계약을 명세한다.

## Behavioral Contract
- 생성: `python build_org_tables.py --db-path salesmap_latest.db --output org_tables.html`로 실행하며, `--org-id` 또는 `--org-name`(LIKE) 필터, `--limit-orgs` 옵션을 지원한다. DB가 없으면 종료한다.
- 데이터 로드: organization/people/deal/memo를 모두 메모리에 적재하고, People/Deal 없는 조직은 제외한다. `_deal_count`를 사람에 부여해 딜 있음/없음 세트를 구분한다.
- UI/흐름:
  - 상단 필터: `기업 규모` 드롭다운(기본 `대기업`이 존재하면 대기업, 없으면 첫 항목/전체) → 조직 드롭다운(필터 결과 중 첫 조직 자동 선택).
  - 레이아웃: 3×3 그리드. 좌측=회사 메모, 중앙(딜 있음)=People→Deal→People 메모→Deal 메모, 우측(딜 없음)=People→(빈)Deal→People 메모→Deal 메모.
  - 선택 동작: 조직 변경 시 stateWith/stateWithout personId/dealId를 모두 리셋하고 모든 테이블 재렌더. People 클릭 시 해당 세트의 Deal/메모 리셋, Deal 클릭 시 Deal 메모만 갱신. Breadcrumb(org/person/deal)이 현재 선택을 표시한다.
  - 포맷: 금액은 1e8 나눠 소수 2자리 `xx.xx억`, 날짜는 문자열에서 날짜 부분만 추출해 표시한다.
### (흡수) 사용 흐름/필터 UI 세부
- 생성 명령: `python build_org_tables.py --db-path salesmap_latest.db --output org_tables.html` 기본이며, `--org-id` 또는 `--org-name`(LIKE, 대소문자 무시)로 조직을 필터링할 수 있다. DB가 없으면 즉시 종료한다.
- 규모 필터 DOM id는 `sizeSelect`이고, 필터 결과 첫 조직을 자동 선택한다. breadcrumb(`crumb-org/person/deal`)가 규모/조직/People/Deal 선택마다 즉시 갱신된다.
- `_deal_count`를 사람에 추가해 딜 있음/없음 세트를 구분하며, 딜 없음 세트에서는 Deal/메모 테이블을 비워둔다. People/Deal 클릭 시 활성 행에 `active` 클래스를 주고 해당 세트의 선택 상태를 리셋한다.

## Invariants (Must Not Break)
- 규모 필터 목록은 DB에서 가져온 size만 사용하며 알파벳 순 + 맨 앞에 `전체`를 추가한다. 기본 선택은 `대기업` 또는 첫 값.
- People “딜 있음” 목록은 `_deal_count > 0`만, “딜 없음”은 `_deal_count == 0`만 표시한다.
- 조직 선택 시 stateWith/stateWithout의 personId/dealId는 항상 null로 초기화되어야 한다.
- 금액 표시는 억 단위 소수 2자리, 데이터 없음은 `-`를 표시한다.
- HTML은 외부 API 호출 없이 임베드된 JSON 데이터만 사용한다.
### (흡수) 추가 불변조건
- breadcrumb(`crumb-org/person/deal`)는 규모/조직/People/Deal 선택 상태를 항상 반영해야 하며, 조직 변경 시 stateWith/stateWithout의 personId/dealId 선택이 모두 초기화된다.
- 규모 목록은 알파벳 정렬 후 `전체`를 prepend하고 기본 선택이 `대기업`이면 이를 우선 사용한다(없으면 첫 값 또는 `전체`).

## Coupling Map
- 생성 스크립트: `build_org_tables.py`(load_data, build_maps, render_html).
- 산출물: `org_tables.html`(인라인 데이터 + 내장 JS/스타일).
- 참조 문서: `10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md`(본 문서가 사용 가이드를 포함).

## Edge Cases & Failure Modes
- 규모 필터 결과가 없으면 조직 드롭다운에 “해당 규모 회사 없음”을 표시하고 테이블을 모두 비운다.
- `_deal_count`가 없는 People은 기본 0으로 처리되어 “딜 없음”에 표시된다.
- DB가 업데이트돼도 HTML은 자동 갱신되지 않으므로 재생성이 필요하다.
 - 조직 필터 결과가 없거나 `_deal_count`가 모두 0이면 crumb/org/person/deal이 빈 상태로 초기화되고 안내 문구를 표시해야 한다.

## Verification
- `python build_org_tables.py --output org_tables.html` 실행 후 파일이 생성되고 stdout에 경로가 출력되는지 확인한다.
- HTML을 열어 규모 필터 기본 선택이 예상대로 설정되고, 조직/People/Deal/메모 클릭 시 breadcrumb와 테이블이 동기화되는지 확인한다.
- People “딜 있음/딜 없음”이 `_deal_count` 기준으로 정확히 분리되고 금액이 억 단위 소수 2자리로 표시되는지 확인한다.
- 규모 필터 결과가 0건일 때 안내 문구와 초기화 동작이 발생하는지 확인한다.
### (흡수) 추가 검증 포인트
- `sizeSelect` 변경 시 첫 조직이 자동 선택되고 crumb-org/person/deal이 즉시 갱신되는지 확인한다.
- `_deal_count`가 누락된 People이 기본 0으로 처리돼 “딜 없음” 목록에만 나타나는지, 조직/필터 결과 없음일 때 모든 표와 breadcrumb가 초기화되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 규모 필터/기본 선택/테이블 렌더링 로직이 내장 JS에만 존재해 다른 UI와 공유되지 않는다.
- 데이터가 HTML에 인라인으로 포함돼 파일 크기가 조직 수에 비례해 증가하며, 데이터 변경 시 재생성이 필수다.
