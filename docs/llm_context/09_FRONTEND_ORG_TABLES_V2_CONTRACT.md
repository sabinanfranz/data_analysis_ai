---
title: org_tables_v2 프런트 계약
last_synced: 2025-12-25
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - dashboard/server/statepath_engine.py
---

# org_tables_v2 프런트 계약

최신 `org_tables_v2.html` 기준으로 메뉴/상태/렌더 계약을 정리한다.

## 메뉴/상태
- 메인: `사업부 퍼포먼스(월별 체결액)`, `2026 Target Board`, `2025 카운터파티 DRI`, `2025 체결액 순위`, `조직/People/Deal 뷰어`, `교육 1팀 딜체크`, `교육 2팀 딜체크`
- 서브: `StatePath 24→25`, (hidden) `2025 대기업 딜·People`, `업종별 매출`, `고객사 불일치`
- 상태: `state`에 activeMenuId/size/rankSize/rankPeopleSize/각 메뉴별 캐시와 모달 핸들 보유. dealMemo/webform/json/statepath 모달은 `bindGlobalModalsOnce`에서 1회 바인딩.

## 사업부 퍼포먼스 > 월별 체결액 (`renderBizPerfMonthly`)
- API: `/performance/monthly-amounts/summary` (기본 2025-01~2026-12, YYMM=2501~2612). 세그먼트 label 예: `기업 고객(삼성 제외)`, `공공 고객`, `온라인(삼성 제외)`, `온라인(기업 고객(삼전 제외))`, `온라인(공공 고객)`, `비온라인(삼성 제외)`, `비온라인(기업 고객(삼전 제외))`, `비온라인(공공 고객)`. key는 기존 유지.
- rows: `TOTAL` → `CONTRACT` → `CONFIRMED` → `HIGH` 4개 고정. 금액은 프런트에서 억 단위 1자리(`formatEok1`) 표기, 헤더/숫자/구분 모두 중앙 정렬. 0은 비활성(span), 나머지는 버튼.
- 클릭: 버튼 클릭 시 `/performance/monthly-amounts/deals?segment=...&row=...&month=YYMM` 호출. `row=TOTAL`은 세 버킷 합집합을 dedupe 후 반환.
- 모달 테이블: 카드/합계 없이 테이블만. 기업명/소속 상위 조직/담당자/딜이름은 좌측 정렬, 딜이름은 20em 폭+ellipsis. 나머지 11개 컬럼(과정포맷/데이원/상태/가능성/수주 예정일/예상 체결액/수강시작일/수강종료일/코스 ID/계약체결일/금액)은 auto-fit(줄바꿈 금지, 잘림 없음)으로 가로 스크롤. 금액 컬럼은 금액>0 우선, 없으면 예상 체결액으로 정렬 후 표시(0이면 `-`).
- 레이아웃: 모달 `.deals-modal-wide`로 `width=min(96vw, 1440px)`, body overflow-x 허용, 테이블 `table-layout:auto` + `width:max-content`.

## 교육 딜체크 (`renderDealCheckScreen`)
- 데이터: `/api/deal-check?team=edu1|edu2` (SQL 딜, 팀 멤버 포함). 리텐션 기준: orgWon2025Total 파싱 성공 ≥ 0.
- 섹션 4개 고정 (순서 유지):
  1) 리텐션 S0/P0/P1/P2 (티어 컬럼 포함, tier=orgWon2025Total 억 단위 기준 Ø/P5~S0)
  2) 신규 온라인(과정포맷 = 구독제(온라인)/선택구매(온라인)/포팅 완전 일치)
  3) 리텐션 P3/P4/P5/기타(티어 컬럼 포함)
  4) 신규 비온라인
- 테이블 공통: 기업/상위 조직 15ch, 담당자 8ch, nowrap+keep-all+ellipsis, 가로 스크롤. 정렬: orgWon2025Total DESC → createdAt ASC → dealId ASC. 메모 버튼: memoCount=0 → “메모 없음” 비활성, >0 → “메모 확인” 모달(YYMMDD, pre-wrap).
- 리텐션 표는 tier 폭을 44~72px로 동적 조정(fitColumnsToContent includeTier=true).

## 2025 체결액 순위 (`renderRank2025Screen`)
- API: `/rank/2025-deals?size=...` 캐시.
- 헤더: 순위/회사/25 티어/24 티어/24년 총액/24→25 배수/25년 총액/25년 온라인/25년 비온라인/26년 타겟/26 온라인/26 비온라인 (억 포맷은 formatAmount).
- 목표액: grade별 multiplier(state.rankMultipliers) 또는 삼성전자 50억 오프라인 목표.
- 회사 클릭 시 navigateToOrg로 조직 뷰어 이동.

## 2025 카운터파티 DRI (`renderRankCounterpartyDriScreen`)
- API: `/rank/2025-top100-counterparty-dri?size=...&limit=100&offset=...`, 온라인 판정=구독제(온라인)/선택구매(온라인)/포팅 완전 일치. 정렬: orgWon2025 DESC → cpTotal2025 DESC. 팀&파트/DRI는 PART_STRUCTURE 매핑(단일 팀·파트면 O).
- 모달: org+upper_org의 딜/팀/People 요약. 딜/소스 표 컬럼 = 이름(딜 링크)/상위 조직/교담자(people 링크)/담당자/금액/과정포맷/계약·예정일/수강시작일/상태/성사가능성/생성일. 25 소스는 온라인·비온라인 테이블, 26은 비온라인 체결만 표시(`26 비온라인 타겟` 제거).

## StatePath 24→25 (`renderStatePathMenu`)
- 헤더: 별도 타이틀 없이 1줄(`sp-header-card`) 구성. 좌측 Primary CTA 필터 버튼(아이콘+라벨+배지, `sp-filter-cta`), 중앙 적용 칩(없으면 연한 “필터 없음” pill), 우측 전체 해제. 필터 배지는 0도 항상 표시하며 필터 적용 시 버튼 `.is-active`로 강조된다. Drawer 열림 시 버튼 `.is-open`.
- 필터 CTA 발견성: 최초 진입 시 sessionStorage `sp_filter_hint_shown`이 없으면 버튼에 `hint-pulse` 애니메이션 2회 적용. CTA는 aria-haspopup="dialog", aria-controls="statepathFilterDrawer".
- 필터 동작: 필터 버튼 → Drawer, 전체 해제 → segment를 `전체`로 되돌리고 클라이언트 필터 리셋 후 `/statepath/portfolio-2425` 재호출. Drawer 필터는 세그먼트/2024 티어/Quick 필터(클라이언트 적용) 유지.
- Snapshot: 6타일(계정수/2024 합계/2025 합계/Δ 합/Company 변화/OPEN·RISK)이 1행 고정, 폭이 좁으면 `.sp-snap-grid`의 `overflow-x:auto`로 가로 스크롤.

## 2026 Target Board (`renderTarget2026Screen`)
- 데이터 로더 재사용(`/rank/2025-top100-counterparty-dri` 대/중견/중소 3회). KPI 8개(2×4 고정, 가로 스크롤/ min-width 960px):
  - 대기업 S0/P0/P1 (삼성전자 S0 제외), 대기업 P2, 대기업 P3~P5, 중견/중소
  - 대기업 S0, P0, P1, P2
- 값: 합계=cpOffline2026, 타겟=cpOffline2025 * tierMultiplier(orgTier). 표시: `{won26_eok}억 / {target26_eok}억` (formatEokNumberOnly → 억 suffix 1회).

## 고객사 불일치 (`renderMismatch2025Screen`)
- API: `/rank/mismatched-deals?size=...` 캐시. 표: 딜 org/People org/딜/고객/계약일/금액/과정포맷/과정 형태. 링크 색상은 대비도 높은 블루/그린을 사용(딜·People 링크도 컬러 적용).

## org/People/Deal 뷰어
- 조직 목록: `/orgs` (People/Deal 존재 조직만, 2025 Won desc → 이름 asc).
- Won 요약: `/orgs/{id}/won-summary` (상위 조직별 23/24/25 Won, 고객/데이원 담당자 리스트).
- 상위 조직별 JSON/compact, StatePath 모달(`/orgs/{id}/statepath`), People/Deal/메모 2×2 컨테이너, 웹폼 모달.

## Verification
- 메뉴 순서가 `2026 Target Board` → `2025 카운터파티 DRI` → `2025 체결액 순위` → `조직/People/Deal 뷰어` → `교육 1/2팀 딜체크` → `StatePath 24→25`로 노출되는지 확인.
- 2025 체결액 순위 헤더가 “25 티어/24 티어/…/26년 타겟/26 온라인/26 비온라인”으로 표기되고 값은 억 포맷인지 확인.
- DRI 모달에서 “상위 조직/교담자” 컬럼과 딜/교담자 링크가 정상 동작하는지 확인.
- 교육 딜체크가 4 섹션(리텐션 S0~P2, 신규 온라인, 리텐션 P3~P5, 신규 비온라인)으로 렌더되고 리텐션 표에만 티어 컬럼이 존재하며 nowrap/가로스크롤 규칙이 적용되는지 확인.
- Target Board KPI가 0이 아니고 cpOffline2025/2026 기반 합산·타겟 계산을 반영하는지 확인(삼성전자 S0 제외).
- 고객사 불일치 표에서 링크 색상이 배경과 명확히 구분되고 링크 클릭 시 조직 뷰어나 Salesmap으로 이동하는지 확인.
- 월별 체결액 카드에서 세그먼트 label이 기업/공공/온라인/비온라인(삼전 제외) 표기로 보이고 rows가 TOTAL→계약 체결→성사 확정→성사 높음 순서로 24개월 금액을 1자리 소수로 표시하는지 확인.
- 월별 체결액 셀 클릭 시 모달이 넓게 열리고(가로 스크롤 가능) 기업명/소속 상위 조직/담당자/딜이름은 좌측 정렬, 나머지 컬럼은 auto-fit으로 잘림 없이 노출되는지 확인.
- 모달 정렬이 금액>0 우선, 없으면 예상 체결액 기준 내림차순(동액 시 딜 이름)인지 확인.
- StatePath 상단에 타이틀이 없고 필터 CTA(아이콘+배지)가 좌측 Primary 버튼으로 노출되는지, Drawer 열림 시 버튼 `.is-open` 스타일이 반영되는지 확인.
- StatePath 필터 0개일 때 연한 “필터 없음” pill이 적용 칩 영역에 표시되고, 전체 해제 클릭 시 segment가 “전체”로 복귀하며 `/statepath/portfolio-2425`를 재호출하는지 확인.
