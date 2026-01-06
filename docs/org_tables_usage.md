---
title: Org Tables Explorer 사용 가이드 (정적 org_tables.html)
last_synced: 2026-01-06
sync_source:
  - build_org_tables.py
  - org_tables.html
  - docs/llm_context/10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md
---

## Purpose
- 정적 HTML(`org_tables.html`)을 생성하는 `build_org_tables.py`의 실행 방법과 UI 동작을 코드 기준으로 설명한다.

## Behavioral Contract
- **생성 명령**: `python build_org_tables.py --db-path salesmap_latest.db --output org_tables.html`이 기본이며, `--org-id` 또는 `--org-name`(LIKE, 대소문자 무시)로 조직을 필터링할 수 있다. DB가 없으면 즉시 종료한다.
- **데이터 로드**: `load_data`가 organization/people/deal/memo 테이블을 불러오며, People/Deal이 모두 없는 조직은 제외한다. `_deal_count` 필드를 사람에 추가해 딜 여부를 구분한다.
- **UI 흐름**:
  - 좌측 드롭다운: `기업 규모` 필터(`sizeSelect`), 기본값은 `대기업`이 있으면 `대기업`, 없으면 첫 값 또는 `전체`. 규모 변경 시 조직 옵션을 재계산한다.
  - 조직 선택: 규모 필터 이후 첫 조직을 자동 선택하며, 선택 시 모든 상태(stateWith/stateWithout)의 personId/dealId를 리셋하고 아래 그리드를 다시 렌더한다.
  - 레이아웃: 3×3 그리드. 좌측 전체는 회사 메모, 중앙은 “딜 있음” People→Deal→People 메모→Deal 메모, 오른쪽은 “딜 없음” People→(빈)Deal→People 메모→Deal 메모.
  - People/Deal 클릭: People 행 클릭 시 해당 세트(stateWith/stateWithout)의 Deal/메모를 리셋하고 활성화 행에 `active` 클래스를 준다. Deal 행 클릭 시 Deal 메모만 갱신한다.
  - 금액/날짜 포맷: 금액은 `formatAmount`로 1e8 나눠 `xx.xx억`, 날짜는 문자열에서 날짜 부분만 추출한다.
- **산출물**: `render_html`가 테이블 데이터를 JSON으로 임베드하고, 최종 HTML을 `--output` 경로에 기록한다. 기본 출력 파일은 `org_tables.html`이며 생성 완료 시 경로를 stdout에 남긴다.

## Invariants (Must Not Break)
- 규모 필터 목록은 DB에 존재하는 size만 사용하며 알파벳 순 정렬 후 맨 앞에 `전체`를 추가한다. 기본 선택은 `대기업` 또는 첫 항목이다.
- 조직 선택 시 stateWith/stateWithout의 personId/dealId가 모두 null로 리셋되고, People/Deal/메모 테이블이 모두 선택 조직 기준으로 재계산된다.
- People “딜 있음” 목록은 `_deal_count > 0`만, “딜 없음” 목록은 `_deal_count == 0`만 포함한다. 딜 없음 세트에서도 Deal/메모 테이블은 비워둔다.
- 금액 표시는 항상 억 단위 소수 2자리이며, 데이터가 없으면 `-`를 표시한다.
- Breadcrumb(`crumb-org/person/deal`)는 현재 stateWith/stateWithout 선택을 기반으로 업데이트되어야 한다.

## Coupling Map
- 데이터 적재/필터: `build_org_tables.py:load_data`, `build_maps`.
- 렌더링/이벤트: `build_org_tables.py:render_html` 내 내장 스크립트(규모 필터, org/person/deal 테이블, 포맷터).
- 산출물: `org_tables.html`을 브라우저로 직접 열어 사용하며 별도 서버나 API를 요구하지 않는다.
- 참고 계약: `docs/llm_context/10_FRONTEND_ORG_TABLES_STATIC_CONTRACT.md`가 정적 버전 상세 스펙을 다룬다.

## Edge Cases & Failure Modes
- 조직 필터 결과가 없으면 조직 드롭다운에 “해당 규모 회사 없음”을 표시하고 상태를 모두 초기화한다.
- `_deal_count`가 없는 People은 기본 0으로 처리되어 “딜 없음” 목록에만 표시된다.
- DB에 없는 size 값을 CLI에서 전달해도 무시되며, org 필터에서 매칭되는 조직이 없으면 프로그램이 종료된다.
- HTML은 DB에 접근하지 않으므로 데이터 갱신 시마다 새로 생성해야 최신 정보가 반영된다.

## Verification
- `python build_org_tables.py --output org_tables.html` 실행 후 파일이 생성되고 stdout에 경로가 출력되는지 확인한다.
- 생성된 HTML을 열어 규모 필터가 `대기업`(또는 첫 항목)으로 기본 선택되고, 조직 선택/People/Deal/메모 클릭 시 좌측 breadcrumb와 표가 동기화되는지 확인한다.
- People “딜 있음/없음” 목록이 `_deal_count` 기준으로 정확히 분리되고, 금액이 억 단위 소수 2자리로 표시되는지 확인한다.
- 조직 필터 결과가 0건일 때 드롭다운에 안내 문구가 표시되고 테이블이 모두 비워지는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 규모 필터 기본값·정렬 로직이 내장 JS에만 존재해 다른 UI와 공유되지 않는다.
- 딜 있음/없음 두 세트가 동일 DOM 구조를 복제하므로 스타일/이벤트 변경 시 두 구역을 함께 수정해야 한다.
- HTML에 데이터가 인라인으로 포함되어 파일 크기가 조직 수에 비례해 증가하며, 데이터 변경 시 재생성이 필수다.
