---
title: 핵심 조회 API 계약 (org_tables_v2.html 사용)
last_synced: 2026-12-11
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - org_tables_v2.html
  - tests/test_perf_monthly_contracts.py
  - tests/test_pl_progress_2026.py
  - tests/test_api_counterparty_dri.py
---

## Purpose
- org_tables_v2 프런트가 의존하는 핵심 FastAPI 엔드포인트의 파라미터/정렬/응답 스키마/캐시 규칙을 최신 코드 기준으로 명세한다.

## Behavioral Contract
- 공통: DB_PATH 기본 `salesmap_latest.db`, 부재 시 대부분 500. 금액/날짜는 원본 TEXT를 그대로 전달하며 포맷은 프런트가 처리한다. 프런트 캐시는 JS Map으로만 존재해 새로고침 전까지 유지된다.
- 조직/기본 조회:
  - `GET /api/sizes` → organization 규모를 알파벳 오름차순으로 반환(프런트가 `"전체"`를 prepend).
  - `GET /api/orgs?size=전체&search=&limit=200&offset=0` → People 또는 Deal이 1건 이상 있는 조직만, won2025 desc→name asc 정렬.
  - `GET /api/orgs/{id}` 404 on missing.
  - `GET /api/orgs/{id}/people?hasDeal=true|false|null` → name asc.
  - `GET /api/orgs/{id}/memos`/`/people/{id}/memos`/`/deals/{id}/memos` → createdAt desc, limit ≤500.
- Won JSON:
  - `GET /api/orgs/{id}/won-groups-json` → organization(id/name/size/industry/industry_major/mid + memos) + groups(upper_org/team별 people/deals). webforms `{name,date}`(id 숨김, webform_history 매핑) 포함, 폼 메모는 `_clean_form_memo`로 정제해 `cleanText`.
- `GET /api/orgs/{id}/won-groups-json-compact` → schema_version `won-groups-json/compact-v1`, deal_defaults(>=80% 반복 필드) 추출, Won 요약(summary) 누적. memos/webforms는 유지하지만 `htmlBody`는 제거되며(텍스트 중심 JSON), text가 비어 있고 htmlBody만 있는 경우 plain text로 보강한다.
  - `GET /api/orgs/{id}/won-summary` → 상위 조직별 Won 합계(2023/2024/2025) + owners/owners2025/dealCount.
- 랭킹/DRI/StatePath:
  - `GET /api/rank/2025/summary-by-size?exclude_org_name=삼성전자&years=2025,2026` → Won 합계 규모별, 캐시 키 `snapshot_version=db_mtime:<int>`.
  - `GET /api/rank/2025-deals`, `/api/rank/2025-deals-people`, `/api/rank/mismatched-deals`, `/api/rank/won-yearly-totals`, `/api/rank/won-industry-summary` → DB 조회 결과 그대로 반환.
  - `GET /api/rank/2025-top100-counterparty-dri?size=대기업` → Lost/Convert 제외, 2025/2026 계약/예상 딜 중 확정/높음/Won만 집계, orgWon2025 desc→cpTotal2025 desc 정렬, owners는 People.owner_json 우선. 기본은 규모별 **전체** 반환이며 limit/offset은 선택 사항.
  - `GET /api/rank/2025-counterparty-dri/detail?orgId=...&upperOrg=...` → 해당 org/upper_org 딜 상세(people_id/people_name/upper_org 포함).
  - 프런트 랭킹 화면은 `/api/rank/2025-deals` 결과만 사용해 26년 타겟을 클라이언트 계산하며, summary-by-size는 별도 캐시 요약용이다.
- `GET /api/statepath/portfolio-2425` → segment/search/정렬/패턴/리스크 필터(OPEN/ScaleUp/회사 전이/셀 이벤트/rail 등)와 limit/offset을 Query로 받아 요약+아이템(금액은 억 단위)을 반환한다. 현재 프런트는 segment/sort/limit만 서버에 전달하고 나머지 필터는 클라이언트 상태로 처리한다. `GET /api/orgs/{id}/statepath-2425`는 단건 버전.
  - `GET /api/orgs/{id}/statepath` → compact JSON 기반 statepath_engine 결과(2024/2025 상태·Path·추천, 금액은 억 단위) 반환.
- 사업부 퍼포먼스:
- `GET /api/performance/monthly-amounts/summary?from=2025-01&to=2026-12&team=edu1|edu2(opt)` → months=YYMM 24개, segment 11종, rows=TOTAL→CONTRACT→CONFIRMED→HIGH. 금액 원 단위, TOTAL은 나머지 합. team 지정 시 day1OwnerNames가 해당 팀 구성원인 딜만 포함. snapshot_version 포함.
- `GET /api/performance/monthly-amounts/deals?segment=...&row=TOTAL|CONTRACT|CONFIRMED|HIGH&month=YYMM&team=edu1|edu2(opt)` → row=TOTAL은 3버킷 합집합 dedupe, totalAmount=amount>0 else expectedAmount 합산, team 지정 시 동일 필터 적용. items 정렬은 프런트가 수행.
  - `GET /api/performance/pl-progress-2026/summary` → Target(T) 열은 `PL_2026_TARGET`, Expected(E)는 기간 비율로 분배한 recognized_by_month 합계(억 단위 소수 4자리). OP_MARGIN은 연간 OP/REV. 캐시 키 `_PL_PROGRESS_SUMMARY_CACHE`.
  - `GET /api/performance/pl-progress-2026/deals?year=2026&month=YYMM&rail=TOTAL|ONLINE|OFFLINE&variant=E` → recognizedAmount desc→amountUsed desc→dealName desc 정렬. variant T는 빈 리스트 반환.
- 딜체크/QC:
  - `GET /api/deal-check?team=edu1|edu2` → `상태='SQL'` 딜 중 팀 구성원 포함 건만, orgWon2025Total desc→createdAt asc→dealId asc, memoCount join. isRetention은 2025 Won 금액 파싱 성공 여부.
  - `GET /api/deal-check/edu1|edu2` → 위 래퍼.
  - `GET /api/qc/deal-errors/summary?team=all|edu1|edu2|public` → QC_RULES(R1~R16) 위배 수 집계. `GET /api/qc/deal-errors/person?owner=...&team=...` → 담당자별 위배 리스트. R13(“고객사 담당자 정보 결측”)은 상태가 convert가 아니고 규모가 대기업/중견기업인 딜에서 상위조직/팀/직급/교육영역 결측을 검사(나머지 조건/예외 동일). R16은 2025-01-01 이후 생성·비온라인·카테고리=생성형AI·규모=대기업·상태=Won인 딜에서 제안서 작성/업로드 여부를 검사(작성 공백 또는 작성≠X인데 업로드 공백이면 위배).
- 카운터파티 리스크:
- `GET /api/report/counterparty-risk?date=YYYY-MM-DD` → 캐시 없으면 `report_scheduler.run_daily_counterparty_risk_job` 실행 후 반환. summary(`tier_groups`, `counts`), `counterparties[]`(`target_2026/coverage_2026/expected_2026/gap/coverage_ratio/pipeline_zero/tier/evidence_bullets/recommended_actions`)와 `meta.db_version`/`data_quality`를 포함한다. `POST /api/report/counterparty-risk/recompute`는 강제 재계산, `GET /api/report/counterparty-risk/status`는 status.json 반환.
### (흡수) 엔드포인트 동작/정렬/필드 스키마 상세
- 공통/기본 데이터: `/api/health`는 항상 `{"status":"ok"}`. `/api/orgs` limit 기본 200(상한 500), `/api/orgs/{id}/memos|/people/{id}/memos|/deals/{id}/memos`는 createdAt desc, limit 상한 500. `/api/initial-data`는 조직/People/Deal/메모 전체를 로딩해 People을 딜 있음/없음으로 분리 후 반환한다.
- Won JSON: `/api/orgs/{orgId}/won-groups-json`은 23/24/25 Won 딜이 있는 상위 조직만 포함하고 organization 블록에 `industry_major/mid`를 포함한다. webforms는 `{name,date}`로 변환해 id를 숨기며 제출이 없거나 history가 없으면 `"날짜 확인 불가"`, 동일 id 다중 제출은 날짜 리스트로 반환한다. 폼 메모는 `_clean_form_memo` 규칙으로 정제하며 전화/규모/업종/채널/동의/utm 키를 드롭한다. `/won-groups-json-compact`는 schema_version=`won-groups-json/compact-v1`, Won 요약 합산/`deal_defaults` 추출까지 동일하게 수행하고 memos/webforms를 유지하되 **`htmlBody` 필드를 제거한다**(텍스트 중심 JSON).
- StatePath: `/api/orgs/{orgId}/statepath`는 compact JSON을 입력으로 statepath_engine 결과(2024/2025 상태, Path 이벤트, Seed, 추천, 금액은 이미 억 단위)를 `{"item": ...}`로 제공한다. `/api/statepath/portfolio-2425`는 Won 딜을 org×lane×rail로 집계해 bucket/이벤트/전이 매트릭스/seed/rail 변화 요약 및 리스트를 반환하며 segment/search/정렬/패턴/리스크 필터와 limit/offset을 Query로 받는다. `/api/orgs/{orgId}/statepath-2425`는 동일 집계의 단건 버전이다.
- 사업부 퍼포먼스: `/api/performance/monthly-amounts/summary`는 2025-01~2026-12 월 키 24개 모두, 세그먼트 11종을 row `TOTAL→CONTRACT→CONFIRMED→HIGH` 순으로 반환한다. `/api/performance/monthly-amounts/deals`는 row=TOTAL일 때 CONTRACT/CONFIRMED/HIGH 합집합을 dedupe 후 반환하고 `totalAmount`를 amount>0 else expected_amount 합산한다. `/api/performance/pl-progress-2026/summary`는 Target(T)=`PL_2026_TARGET`, Expected(E)=`recognized_by_month` 합산(억 단위)이며 `/performance/pl-progress-2026/deals`는 E 변형만 지원하고 recognizedAmount desc→amountUsed desc→dealName desc 정렬을 반환한다.
- 딜체크/QC: `/api/deal-check?team=edu1|edu2`는 `PART_STRUCTURE` 포함 담당자와 상태='SQL' 딜만 orgWon2025Total desc→createdAt asc→dealId asc로 반환하고 memoCount를 left join한다. deal."기획시트 링크" 컬럼이 존재하면 `planningSheetLink`로 그대로 내려주며, 컬럼이 없거나 값이 비어 있으면 `null`을 준다. `/api/qc/deal-errors/summary|person`는 QC_RULES(R1~R16) 위배 건수를 팀별/담당자별로 계산하며 R13은 규모 대기업/중견기업 + 상태≠convert 조건에서 상위조직/팀/직급/교육영역 결측을 검사하고, R16은 2025-01-01 이후 생성·비온라인·카테고리=생성형AI·규모=대기업·상태=Won 딜에서 제안서 작성/업로드 여부를 검사한다.
- 카운터파티 리스크: `/api/report/counterparty-risk`는 캐시(`report_cache/YYYY-MM-DD.json`)가 없으면 `report_scheduler.run_daily_counterparty_risk_job`을 실행해 생성 후 summary/counts/data_quality/meta.db_version과 counterparties(`target_2026/coverage_2026/expected_2026/gap/coverage_ratio/pipeline_zero/tier/evidence_bullets/recommended_actions`)를 포함해 반환하고, `/api/report/counterparty-risk/status`는 status.json을 그대로 내려준다. DB가 수정 중이면 `DB_STABLE_WINDOW_SEC` 내에서는 실패로 기록된다.

## Invariants (Must Not Break)
- `/api/orgs` 정렬: won2025 desc → name asc, People/Deal 둘 다 0이면 제외.
- Won JSON 그룹: 2023/2024/2025 Won upper_org만 포함, webform id 미노출, webform 날짜는 `"날짜 확인 불가"`/단일/리스트 형태.
- 월별 체결액: months 24개, rows TOTAL→CONTRACT→CONFIRMED→HIGH 고정, segment label은 `_perf_segments` 정의(삼성/기업/공공/온라인/비온라인) 그대로 반환.
- P&L: columns 연간(T/E) → 월별(T/E) 순, Expected만 드릴다운 지원, Target 값은 `PL_2026_TARGET` 딕셔너리 그대로 사용.
- DRI: Lost/Convert 제외, prob 확정/높음/Won만 카운터파티 합산, owners는 People.owner_json을 우선 사용한다.
- 딜체크: memoCount left join, isRetention은 2025 Won 금액 파싱 성공 기준(예상 체결액 미사용).
- 캐시 키: DB mtime을 포함하는 메모리 캐시(`_COUNTERPARTY_DRI_CACHE`, `_PERF_MONTHLY_*`, `_PL_PROGRESS_*`, `_RANK_2025_SUMMARY_CACHE`)가 있어 프로세스 재시작 전까지 새 DB가 반영되지 않을 수 있다.
### (흡수) 불변조건·정렬·캐시
- `/api/orgs` 정렬은 won2025 desc→name asc 고정이며 People/Deal이 모두 0이면 제외된다.
- Won JSON은 23/24/25 Won 딜 upper_org만 포함하고 webform id는 노출하지 않는다. `_clean_form_memo`는 utm_source 또는 “고객 마케팅 수신 동의”가 없는 경우 정제를 스킵하며 전화/규모/업종/채널/동의/utm 키를 항상 제거한다.
- 월별 체결액 요약은 months 24개, row 순서 TOTAL→CONTRACT→CONFIRMED→HIGH, 세그먼트 label은 `_perf_segments` 정의와 동일하게 고정된다.
- P&L 진행율매출은 T/E 두 variant를 모두 포함하고 E는 `recognized_by_month`를 억 단위 소수 4자리로 반영한다. T 변형 드릴다운은 항상 빈 리스트다.
- 딜체크 정렬은 orgWon2025Total desc→createdAt asc→dealId asc 고정이며 memoCount join 규칙이 변하면 안 된다.
- 카운터파티 리스크는 summary.tier_groups에 S0/P0/P1, P2 그룹을 포함해야 하고 counterparties에는 coverage_ratio/gap/pipeline_zero/meta.db_version/data_quality가 항상 존재해야 한다.

## Coupling Map
- 라우터: `dashboard/server/org_tables_api.py` ↔ DB 로직 `dashboard/server/database.py` ↔ 보조 모듈(`json_compact.py`, `statepath_engine.py`, `report_scheduler.py`).
- 프런트: `org_tables_v2.html` fetch 래퍼가 모든 `/api/*`를 호출해 화면 렌더/모달/캐시를 담당.
- 테스트: `tests/test_perf_monthly_contracts.py`, `tests/test_pl_progress_2026.py`, `tests/test_api_counterparty_dri.py`, `tests/test_won_groups_json.py`, `tests/test_deal_check_edu1.py` 등으로 계약 검증.

## Edge Cases & Failure Modes
- DB 없음/잠금 시 500. 캐시가 활성화된 엔드포인트는 DB 교체 후에도 이전 snapshot_version으로 응답할 수 있다.
- 월/segment/row/rail 등 파라미터가 잘못되면 400을 반환한다.
- webform_history 테이블이 없거나 비어 있으면 webforms date가 `"날짜 확인 불가"`로 채워진다.
- P&L summary는 start/end/amount 누락 딜을 meta.excluded에 집계 후 제외한다; variant T는 드릴다운이 빈 결과다.
- 카운터파티 리포트는 DB_STABLE_WINDOW_SEC 내에 DB 수정 중이면 실패하고 status.json에 `DB_UNSTABLE_OR_UPDATING`이 기록된다.
### (흡수) 캐시/락/파라미터 오류
- DB가 없거나 수정 중이면 대부분 500을 반환하고 `/api/report/counterparty-risk`는 status.json에 실패 기록을 남길 수 있다.
- `/api/rank/2025/summary-by-size` 등 캐시 키가 DB mtime을 포함해 DB 교체 후 FastAPI를 재시작하지 않으면 이전 캐시가 남는다.
- `/api/performance/*`는 잘못된 month(YYMM)나 segment/row 키 요청 시 400을 반환하며, Counterparty Risk는 date 파라미터 파싱 실패 시 400을 반환한다.
- compact 변환은 memos/webforms를 제거하지 않으므로 개인정보 제거 용도로 사용할 수 없다.

## Verification
- `/api/orgs`가 won2025 desc→name asc이고 People/Deal 0건 조직이 제외되는지 샘플 DB로 확인한다.
- `/api/orgs/{id}/won-groups-json`에 industry_major/mid, webforms `{name,date}`, cleanText 메모가 포함되고 upper_org가 Won 존재 조직만 있는지 확인한다.
- `/api/performance/monthly-amounts/summary`가 24개월·4개 row·11세그먼트를 포함하고 `/performance/monthly-amounts/deals` row=TOTAL이 3버킷 합집합인지 검증한다. team 파라미터 적용 시 day1OwnerNames 기준 필터가 동작하는지 확인한다.
- `/api/performance/pl-progress-2026/summary`가 연간/월별 T/E 컬럼을 포함하고 current YYMM E 셀 클릭 시 `/performance/pl-progress-2026/deals`가 recognizedAmount desc→amountUsed desc→dealName desc 정렬인지 확인한다.
- `/api/rank/2025-top100-counterparty-dri`가 Lost/Convert 제외, orgWon2025 desc→cpTotal2025 desc 정렬이며 owners가 People.owner_json 우선으로 채워지는지 테스트 대비 확인한다.
- `/api/deal-check?team=edu1|edu2`가 orgWon2025 desc→createdAt asc→dealId asc 정렬이며 memoCount/personId/personName/orgWon2025Total/planningSheetLink(null 포함)을 포함하는지 확인한다.
- `/api/report/counterparty-risk` 호출 시 캐시 생성/재사용, status.json 업데이트가 정상인지 확인한다.
### (흡수) 엔드포인트별 세부 검증
- `/api/statepath/portfolio-2425`가 segment/search/정렬/패턴/리스크 필터와 limit/offset을 모두 반영해 bucket/전이/seed/rail 변화 요약 및 리스트를 반환하는지 확인한다.
- `/api/performance/pl-progress-2026/deals`가 E 변형만 지원하고 recognizedAmount desc→amountUsed desc→dealName desc 정렬인지, 월별 E 셀만 클릭 가능하도록 프런트 동작이 맞는지 검증한다.
- `/api/report/counterparty-risk` 캐시 미존재 시 `report_scheduler.run_daily_counterparty_risk_job`가 실행돼 summary/counts/data_quality/meta.db_version과 counterparties 필드가 포함되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 캐시가 DB mtime 기반 메모리에만 존재해 프로세스 재시작 전까지 새 DB가 반영되지 않는다.
- 온라인 판정/PL_2026_TARGET 등 상수가 `database.py`와 프런트에 중복돼 있어 수정 시 양방향 반영이 필요하다.
- 딜체크/DRI/StatePath/월별/PL 등 다양한 기능이 모두 `database.py`에 집중되어 변경 영향 범위가 크다.
### (흡수) 추가 리팩터링 고려
- mtime 기반 메모리 캐시(`_COUNTERPARTY_DRI_CACHE`, `_PERF_MONTHLY_*`, `_PL_PROGRESS_SUMMARY_CACHE`)가 FastAPI 재시작 전에는 DB 교체를 반영하지 못해 운영 시 재시작 절차가 필요하다.
- StatePath/DRI/QC 등 다수 엔드포인트가 `database.py` 단일 파일에 집중되어 있어 함수 분할과 상수 공유 모듈화가 필요하다.
