---
title: org_tables_v2 동작 정리 (FastAPI 기반)
last_synced: 2025-12-24
sync_source:
  - org_tables_v2.html
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - dashboard/server/statepath_engine.py
  - docs/llm_context/09_FRONTEND_ORG_TABLES_V2_CONTRACT.md
  - dashboard/server/database.py
---

# org_tables_v2 동작 정리 (FastAPI 기반)

`org_tables_v2.html`는 정적 HTML+JS로 동작하며, FastAPI 백엔드(`/dashboard/server`)의 `/api`를 호출한다. 메뉴/화면 흐름, 주요 엔드포인트, UI 규칙을 최신 코드 기준으로 정리한다.

## 실행/접속
- 백엔드: `uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload` (DB 기본 `salesmap_latest.db`).
- 프런트: 브라우저에서 `org_tables_v2.html` 열기. 파일 직접 열면 API_BASE=`http://localhost:8000/api`, 서버 배포 시 현재 origin+`/api`.
- ORG_LIMIT=200, People/Deal 없는 조직은 목록에서 제외.

## 메뉴(사이드바)
순서: `사업부 퍼포먼스`(월별 체결액) → `2026 Target Board` → `2025 카운터파티 DRI` → `2025 체결액 순위` → `조직/People/Deal 뷰어` → `교육 1팀 딜체크` → `교육 2팀 딜체크` → `StatePath 24→25` → (서브) `고객사 불일치` (일부 서브 메뉴는 hidden 처리).

## 주요 API (`dashboard/server/org_tables_api.py`)
- `/sizes`, `/orgs`, `/orgs/{id}`, `/orgs/{id}/memos`, `/orgs/{id}/people`, `/people/{id}/deals|memos`, `/deals/{id}/memos`
- `/rank/2025-deals`, `/rank/2025/summary-by-size`, `/rank/2025-deals-people`, `/rank/2025-top100-counterparty-dri`, `/rank/mismatched-deals`, `/rank/won-yearly-totals`, `/rank/won-industry-summary`
- `/orgs/{id}/won-summary`, `/orgs/{id}/won-groups-json`, `/orgs/{id}/won-groups-json-compact`, `/orgs/{id}/statepath`, `/api/statepath/portfolio-2425`

## 화면별 요약
### 사업부 퍼포먼스 > 월별 체결액
- 데이터: `/performance/monthly-amounts/summary` (기본 2025-01~2026-12, YYMM=2501~2612). 세그먼트 label은 `기업 고객(삼성 제외)`, `공공 고객`, `온라인(삼성 제외)`, `온라인(기업 고객(삼전 제외))`, `온라인(공공 고객)`, `비온라인(삼성 제외)`, `비온라인(기업 고객(삼전 제외))`, `비온라인(공공 고객)` 등으로 표시되며 key는 기존 유지.
- 행: `TOTAL → 계약 체결(CONTRACT) → 성사 확정(CONFIRMED) → 성사 높음(HIGH)` 4개 고정. 금액은 프런트에서 억 단위 1자리(`formatEok1`)로 표기, 헤더/숫자/구분 모두 가운데 정렬.
- 셀: 금액 0이면 비활성(span), 0 초과는 버튼으로 렌더. 클릭 시 `/performance/monthly-amounts/deals?segment=...&row=...&month=YYMM` 호출, `row=TOTAL`은 세 버킷 합집합.
- 모달: 테이블만 표시(안내/합계 카드 없음). 딜이름은 20em 폭 고정+ellipsis, 기업명/소속 상위 조직/담당자/딜이름은 좌측 정렬. 나머지 11개 컬럼은 auto-fit(과정포맷/데이원/상태/가능성/수주 예정일/예상 체결액/수강시작일/수강종료일/코스 ID/계약체결일/금액). 정렬은 금액>0 우선, 없으면 예상 체결액 기준 내림차순 후 이름 오름차순.
- 스타일: 모달 폭 `deals-modal-wide`로 min(96vw, 1440px), 가로 스크롤 허용, 테이블 auto 레이아웃으로 값 길이만큼 확장.

### 2025 체결액 순위
- 데이터: `/rank/2025-deals?size=...` 캐시. 헤더: `순위/회사/25 티어/24 티어/24년 총액/24→25 배수/25년 총액/25년 온라인/25년 비온라인/26년 타겟/26 온라인/26 비온라인` (억 포맷은 formatAmount 사용).
- 목표액: grade별 배수(state.rankMultipliers) 또는 삼성전자 50억 하드코딩(오프라인 목표).
- 회사 클릭 시 org 뷰어로 이동(navigateToOrg).

### 2025 카운터파티 DRI
- 데이터: `/rank/2025-top100-counterparty-dri?size=...&limit=100&offset=...` (온라인=구독제(온라인)/선택구매(온라인)/포팅).
- 표: 기업명/티어/카운터파티/25 온라인/25 비온라인/25 담당자/팀&파트/DRI. 정렬: orgWon2025 desc → cpTotal2025 desc.
- 상세 모달: 선택 org/upper_org의 딜/People/팀 합계를 표시. 딜 표와 25/26 소스 표 컬럼 = `이름(세일즈맵 링크)/상위 조직/교담자(people 링크)/담당자/금액/과정포맷/계약·예정일/수강시작일/상태/성사가능성/생성일`. 25 소스는 온라인/비온라인 테이블로 분리, 26은 비온라인 체결만 표시(`26 비온라인 타겟` 제거).

### 2026 Target Board
- 데이터: DRI 데이터 로더 재사용(`/rank/2025-top100-counterparty-dri` 대/중견/중소 3회). KPI 8개(2×4): 대기업 S0/P0/P1(삼성전자 S0 제외), P2, P3~P5, 중견/중소, 그리고 S0/P0/P1/P2 단일 그룹. 합계 = cpOffline2026 합, 타겟 = cpOffline2025 * tierMultiplier. 표시는 “26 비온라인 체결액 Target”으로 억 단위 숫자만 포맷 후 “억” suffix 1회.

### 교육 1/2팀 딜체크
- 데이터: `/api/deal-check?team=edu1|edu2` (SQL 딜, 팀 멤버 포함). orgWon2025Total 파싱 성공 ≥0이면 리텐션.
- 섹션 4개 고정: (1) 리텐션 S0/P0/P1/P2 (티어 컬럼 포함) (2) 신규 온라인 (3) 리텐션 P3/P4/P5/기타 (티어 포함) (4) 신규 비온라인. 온라인 판정은 구독제(온라인)/선택구매(온라인)/포팅 완전 일치.
- 정렬: orgWon2025Total DESC → createdAt ASC → dealId ASC. 테이블 줄바꿈 금지(nowrap/keep-all/ellipsis), 가로 스크롤. 폭: org/upper/team=15ch, person=8ch, memo 버튼은 측정(clamp 72~140), 나머지 동적. 리텐션 테이블은 tier 폭 44~72px 자동 조정.
- 메모: memoCount=0 → “메모 없음” 비활성, >0 → “메모 확인” 버튼. 모달 ESC/X/오버레이 닫기, 날짜 YYMMDD, 내용 pre-wrap 1.5em.

### 조직/People/Deal 뷰어
- 조직 목록: People 또는 Deal 존재 조직만, 2025 Won DESC → 이름 ASC, 기본 limit=200.
- Won 요약: `/orgs/{id}/won-summary`로 상위 조직별 23/24/25 Won 합계, 고객/데이원 담당자 리스트.
- 상위 조직 People/Deal/메모 2×2 컨테이너 + 상위 조직별 JSON/compact, StatePath 모달.

### 고객사 불일치
- 데이터: `/rank/mismatched-deals?size=...` 캐시. 표: 딜 org/People org/딜/고객/계약일/금액/과정포맷/과정 형태. 회사/딜/People 링크는 명확한 블루/그린 색상으로 표시.

## Verification
- 사이드바에 `사업부 퍼포먼스`가 최상단, 이어서 `2026 Target Board`, `2025 카운터파티 DRI`, `2025 체결액 순위`, `조직/People/Deal 뷰어`, `교육 1/2팀 딜체크`, `StatePath 24→25` 순서로 보이는지 확인.
- 월별 체결액 카드에서 세그먼트 label이 기업 고객/공공/온라인/비온라인(삼전 제외) 표기로 노출되고 rows가 TOTAL→계약 체결→성사 확정→성사 높음 순서인지 확인.
- 월별 체결액 숫자가 1자리 소수로 가운데 정렬돼 있고 0은 비활성, 클릭 시 해당 세그먼트/월 모달이 열리는지 확인.
- 모달 딜 테이블에서 기업명/소속 상위 조직/담당자/딜이름이 좌측 정렬이고 딜이름이 20em 폭+ellipsis, 나머지 11개 컬럼이 값 길이에 따라 가로 스크롤로 표시되는지 확인.
- 모달 정렬이 금액>0 우선, 없으면 예상 체결액 기준 내림차순(동액 시 이름 오름차순)으로 적용되는지 확인.
- 2025 체결액 순위 헤더가 `25 티어/24 티어/24년 총액/25년 총액/25 온라인/25 비온라인/26년 타겟/26 온라인/26 비온라인`으로 노출되고 값이 억 단위 포맷인지 확인.
- DRI 모달에서 딜/교담자 링크가 작동하고 “상위 조직/교담자” 컬럼이 보이는지 확인.
- 교육 1/2팀 딜체크가 4섹션(리텐션 S0~P2, 신규 온라인, 리텐션 P3~P5, 신규 비온라인)으로 나뉘고 리텐션 표에만 티어 컬럼이 표시되며 nowrap/가로 스크롤 규칙이 적용되는지 확인.
- 고객사 불일치 표에서 링크 색상이 배경과 충분히 대비되고 각 링크가 조직 뷰어나 Salesmap으로 이동하는지 확인.
