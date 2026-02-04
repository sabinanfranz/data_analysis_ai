---
title: 랭킹/집계/DRI API 계약
last_synced: 2026-02-04
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/statepath_engine.py
  - org_tables_v2.html
  - tests/test_api_counterparty_dri.py
---

## Purpose
- 랭킹·DRI·이상치·요약 계열 FastAPI 엔드포인트의 파라미터/정렬/응답 스키마 및 캐시 규칙을 코드 기준으로 명시한다.

## Behavioral Contract
### 랭킹 합계
- `GET /api/rank/2025-deals?size=전체`
  - 조건: `deal."상태"='Won'` AND 계약연도=2025. size 필터는 organization."기업 규모" 정확 일치(전체면 무시).
  - 그룹: organizationId. 필드 `orgId, orgName, totalAmount, onlineAmount, offlineAmount, totalAmount2024, grade, grade2024, formats[]` (course_format별 합계). 정렬 totalAmount DESC.
- `GET /api/rank/2025-deals-people?size=대기업`
  - 대상: 2025 Won 딜이 있는 조직. 상위조직/팀 모두 미입력인 행은 제외. 필드 `orgId, orgName, upper_org, team, personId, personName, title_signature, edu_area, won2025, dealCount, deals[]`. 정렬 won2025 DESC.
- `GET /api/rank/mismatched-deals?size=대기업`
  - 조건: deal.organizationId ≠ people.organizationId. 필드 `dealId, dealName, dealOrgId/Name, personId/Name, personOrgId/Name, contract_date, amount, course_format`. 정렬 contract_date DESC NULLS LAST.
- `GET /api/rank/won-yearly-totals`
  - 조건: status=Won, 연도 ∈ {2023,2024,2025}. 반환 `items[{year, size, totalAmount, orgCount}]` by industry? (실제는 규모별 합계) with SUM by size. 정렬 합계 DESC.
- `GET /api/rank/won-industry-summary?size=전체`
  - 조건: status=Won, 연도 2023/2024/2025. 그룹: 업종 구분(대). 필드 `industryMajor, orgCount, totalAmountByYear{2023,2024,2025}`. 정렬 2025 금액 DESC.
- `GET /api/rank/2025/summary-by-size?exclude_org_name=삼성전자&years=2025,2026`
  - 조건: status=Won, 계약연도 in years. exclude_org_name 정확 일치 제외. 응답 `by_size{size:{y2025,y2026}}, totals, snapshot_version=db_mtime:int`.

### 카운터파티 DRI / Targetboard 2026
- `GET /api/rank/2025-top100-counterparty-dri?size=대기업&limit=&offset=&debug=false`
  - 조건: Lost/Convert 제외, 2025/2026 계약 또는 예상일이 있는 딜 중 probability ∈ {확정,높음} 또는 status=Won. ONLINE 판정은 `statepath_engine.ONLINE_COURSE_FORMATS`(구독제(온라인), 선택구매(온라인), 포팅).
  - owners 우선순위: People.owner_json → deal.owner_json. 필드 `orgId, orgName, sizeRaw, orgTier, orgWon2025, upperOrg, cpOnline2025, cpOffline2025, cpOnline2026, cpOffline2026, owners2025, dealCount2025, target26Offline, target26Online, target26OfflineIsOverride, target26OnlineIsOverride`.
  - 정렬: orgWon2025 DESC → cpTotal2025 DESC. limit(1–200000)·offset(>=0) 선택, 미지정 시 전체 반환. meta에 orgCount(rowCount), offset/limit, snapshot_version, targetsVersion.
  - 특수: counterparty_targets_2026.xlsx에만 있고 DB에 없는 (org,upper)도 orgTier='N' row로 포함하며 target26* override/flag는 유지, 금액은 0.
- `GET /api/rank/2025-top100-counterparty-dri/targets-summary?size=대기업`
  - 규모별 cp/target/expected 합계와 override 적용 건수를 totals에 담고 meta에 snapshot_version+targets_version 포함.
- `GET /api/rank/2025-counterparty-dri/detail?orgId=&upperOrg=`
  - 해당 org/upper_org 딜 상세. 필드 people_id/people_name/upper_org 포함. 404 if missing.

### 기타 집계/이상치
- `GET /api/ops/2026-online-retention`
  - 조건: status=Won, 생성일 ≥2024-01-01, 과정포맷 ∈ ONLINE_COURSE_FORMATS, start/end 필수, end 2024-10-01~2027-12-31 범위 필터, course_id 존재 필수. 정렬 endDate ASC → orgName ASC → dealId ASC. meta{db_version,rowCount}.
- QC 숨김 규칙 R17은 응답에서 제외되며 deal-errors summary/person은 R1~R16만 노출.

## Invariants (Must Not Break)
- ONLINE 판정 세트는 정확히 `구독제(온라인)`, `선택구매(온라인)`, `포팅`.
- `/rank/2025-deals`는 status=Won, 연도=2025만 포함하고 totalAmount DESC 정렬.
- DRI 정렬: orgWon2025 DESC → cpTotal2025 DESC; owners는 People.owner_json 우선.
- Target summary/targets_version/snapshot_version이 항상 포함되어야 한다(limit/offset 관계 없음).
- ops 2026 retention: start/end/amount/course_id 누락 시 제외, amount<=0 제외.

## Coupling Map
- 라우터: `org_tables_api.py` ↔ 집계: `database.py` (`get_rank_*`, `get_ops_2026_online_retention` 등) ↔ ONLINE 포맷 상수 `statepath_engine.ONLINE_COURSE_FORMATS`.
- 프런트: `org_tables_v2.html`의 Rank/Targetboard/온라인 리텐션 화면(fetchRankData, renderRankCounterpartyDriScreen, renderOnlineRetention2026Screen).
- 테스트: `tests/test_api_counterparty_dri.py`(owners/정렬/limit/override), `tests/test_api_online_retention_2026.py`(필터/정렬), `tests/test_mismatched_deals_2025.py`, `tests/test_rank_2025_deals.py`, `tests/test_rank_2025_deals_people.py`, `tests/test_won_totals_by_size.py` 등.

## Edge Cases & Failure Modes
- size 파라미터 오입력 시 필터 미적용(전체). exclude_org_name 미일치 시 전부 포함.
- counterparty_targets에만 존재하는 (org, upper) 조합은 orgTier='N'으로 포함되지만 org 목록에 없으면 owners가 비어 있을 수 있다.
- ops 2026 retention에서 날짜/금액/코스ID 누락, 온라인 포맷 외, 금액<=0은 즉시 제외되어 rowCount가 줄어든다.
- 캐시: summary-by-size와 DRI/targets-summary는 DB mtime + targets_version 캐시가 메모리에 남아 DB 교체 후 재시작 전까지 이전 데이터를 반환할 수 있다.

## Verification
- `curl -s "http://localhost:8000/api/rank/2025-deals?size=대기업" | jq '.items[0]'` → status Won, 연도 2025, totalAmount DESC 확인.
- `curl -s "http://localhost:8000/api/rank/2025-deals-people" | jq '.items[0].upper_org'` → upper_org/team 미입력만인 행 제외 여부 확인.
- `curl -s "http://localhost:8000/api/rank/mismatched-deals" | jq '.items | length'` → orgId≠peopleOrgId만 포함되는지 확인.
- `curl -s "http://localhost:8000/api/rank/2025-top100-counterparty-dri?limit=5" | jq '.items[0].orgWon2025, .items[0].target26OfflineIsOverride'` → 정렬/override 필드 포함 확인, meta.targetsVersion 존재 확인.
- `curl -s "http://localhost:8000/api/ops/2026-online-retention" | jq '.meta.rowCount, .items[0].courseFormat, .items[0].amount'` → 온라인 3포맷, 금액>0, start/end 존재 확인.
