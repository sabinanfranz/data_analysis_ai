---
title: 정적 org_tables.html 프런트 계약
last_synced: 2026-02-04
sync_source:
  - build_org_tables.py
  - org_tables.html
  - tests/test_build_org_tables.py
---

## Purpose
- `build_org_tables.py`가 생성하는 정적 테이블 탐색기(`org_tables.html`)의 데이터/동작 계약을 정의한다.

## Behavioral Contract
- 생성 CLI: `python build_org_tables.py --db-path salesmap_latest.db --output org_tables.html [--org-id <id> | --org-name <substr>] [--limit-orgs N]`.
  - org-id 정확 일치 또는 org-name LIKE(소문자 변환)로 조직을 필터링. DB 없으면 종료.
- 데이터 적재: organization/people/deal/memo 전부 메모리에 로드. People/Deal 둘 다 없는 조직은 제외. 사람마다 `_deal_count`를 추가해 딜 있음/없음 세트를 분리.
- 레이아웃/흐름:
  - 상단 필터: `기업 규모(sizeSelect)` 드롭다운 → `조직(orgSelect)` 드롭다운. 규모 옵션은 DB distinct size를 알파벳 정렬해 `전체`를 맨 앞에 추가, 기본 선택은 `대기업`이 있으면 대기업, 없으면 첫 값.
  - 3×3 그리드: 좌(회사 메모), 중앙(딜 있음: People→Deal→People 메모→Deal 메모), 우(딜 없음: People→(빈)Deal→People 메모→Deal 메모). `orgMemoCard`는 메모가 없으면 `has-memos` 클래스 제거.
  - 선택 규칙: 조직 변경 시 stateWith/stateWithout의 personId/dealId를 null로 초기화하고 모든 테이블 재렌더. People 클릭 시 해당 세트의 dealId 초기화, Deal 클릭 시 Deal 메모만 갱신. breadcrumb(`crumb-org/person/deal`)는 항상 현재 선택을 반영.
- 표시 규칙: 금액은 1e8 나눠 소수 2자리(`xx.xx억`), 날짜는 문자열에서 날짜 부분만 추출해 표시, 데이터 없으면 `-`.
- 렌더 데이터 출처: 인라인 JSON `<script id="data">`로 주입되며 외부 fetch 금지.

## Invariants (Must Not Break)
- 규모 옵션은 DB에서 가져온 값만 사용 + `전체` prepend, 기본 선택 로직(대기업 우선 → 첫 값) 고정.
- People “딜 있음” 목록은 `_deal_count>0`만, “딜 없음”은 `_deal_count==0`만 포함.
- 조직 변경 시 stateWith/stateWithout의 personId/dealId가 항상 초기화되고 breadcrumb가 갱신되어야 한다.
- 외부 네트워크 호출이 없어야 하며 모든 데이터는 HTML 내에 포함되어야 한다.

## Coupling Map
- 생성 스크립트: `build_org_tables.py`(load_data → build_maps → render_html).
- 산출물: `org_tables.html`(인라인 데이터 + 내장 JS/CSS).
- 테스트: `tests/test_build_org_tables.py`가 CLI/필터/랜더 기본값을 검증한다.

## Edge Cases & Failure Modes
- 규모 필터 결과가 0건이면 orgSelect에 “해당 규모 회사 없음”을 표시하고 모든 테이블/crumb를 비운다.
- `_deal_count` 누락 → 기본 0으로 처리되어 “딜 없음” 목록에만 표시.
- DB가 갱신되어도 HTML은 자동 갱신되지 않으므로 재생성이 필요하다.

## Verification
- `python build_org_tables.py --output org_tables.html` 실행 후 파일 생성/경로 출력 확인.
- HTML 열어 기본 규모 선택, 조직 자동 선택, breadcrumb 동기화, People/Deal 클릭 시 active 클래스 및 테이블/메모 업데이트 확인.
- 딜 있음/없음 분리와 금액 포맷(`xx.xx억`) 확인, 규모 결과 0건일 때 안내/초기화 동작 확인.

## Refactor-Planning Notes (Facts Only)
- 모든 로직이 단일 HTML/JS에 내장돼 다른 UI와 공유되지 않는다.
- 데이터 인라인 방식이라 조직 수가 늘면 파일이 커지고, DB 변경 시 스크립트를 다시 실행해야 한다.
