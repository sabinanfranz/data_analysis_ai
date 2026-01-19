---
title: 랭킹/집계/이상치 API 계약
last_synced: 2026-12-11
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - org_tables_v2.html
  - tests/test_api_counterparty_dri.py
---

## Purpose
- 랭킹/집계/이상치/DRI 관련 FastAPI 엔드포인트의 필터/정렬/응답 스키마를 코드 기준으로 명세한다.

## Behavioral Contract
- 공통: 금액은 원 단위 TEXT → `_to_number`로 변환 후 반환, 프런트가 억 단위로 표시한다. 연도 필터는 `"계약 체결일"` 앞 4자리(없으면 `_year_from_dates`/`_parse_year_from_text`)를 사용한다. 규모 필터는 `size`(기본 전체) 파라미터가 있을 때만 적용한다.
- `GET /api/rank/2025-deals`: 상태 Won, 계약연도 2025. 그룹=orgId. 필드 `orgId/orgName/industryMajor/industryMid/totalAmount/onlineAmount/offlineAmount/grade/totalAmount2024/grade2024/formats[]`. 정렬 totalAmount desc.
- `GET /api/rank/2025-deals-people`: 2025 Won 딜이 있는 조직만 대상, 상위 조직/팀 미입력만인 경우 제외. 필드 `orgId/orgName/upper_org/team/personId/personName/title_signature/edu_area/won2025/dealCount/deals[]`. 정렬 won2025 desc.
- `GET /api/rank/mismatched-deals`: deal.organizationId ≠ people.organizationId. 필드 `dealId/dealName/dealOrgId/Name/personId/Name/personOrgId/Name/contract_date/amount/course_format/course_shape`.
- `GET /api/rank/won-yearly-totals`: Won 상태, 계약연도 2023/2024/2025. 규모별 합계 `won2023/2024/2025`, 정렬 합계 desc.
- `GET /api/rank/won-industry-summary`: Won 상태, 계약연도 2023/2024/2025, 선택 규모 필터. 업종 구분(대)별 합계/조직 수.
- `GET /api/rank/2025/summary-by-size?exclude_org_name=삼성전자&years=2025,2026`: Won 상태, 계약연도 years. exclude_org_name 정확히 일치 시 제외. 반환 `by_size{size:sum_2025,sum_2026}`, totals, snapshot_version=`db_mtime:<int>`.
- `GET /api/rank/2025-top100-counterparty-dri?size=대기업`: Lost/Convert 제외. 2025/2026 계약/예상일이 있는 확정/높음/Won 딜만 집계. ONLINE 판정=`statepath_engine.ONLINE_COURSE_FORMATS`. owners2025는 People.owner_json 우선, 없으면 deal.owner_json. 필드 `orgId/orgName/sizeRaw/orgTier/orgWon2025/upperOrg/cpOnline2025/cpOffline2025/cpOnline2026/cpOffline2026/owners2025/dealCount2025` + 선택적 `target26Offline/target26Online`(override 여부는 `target26OfflineIsOverride/target26OnlineIsOverride`). 정렬 orgWon2025 desc → cpTotal2025 desc. 기본은 규모별 **전체** 반환이며 limit/offset은 선택 사항(meta에 offset/limit/orgCount/rowCount 포함). **추가 규칙**: counterparty_targets_2026.xlsx에만 존재하고 딜이 없는 (기업명, 카운터파티) 조합도, 조직명 정확 일치 + People.upper_org 정규화 일치 시 orgTier=`N`인 row로 추가해 응답에 포함되며, cp* 값은 0, target26*은 엑셀 override 적용 값(없으면 0)과 override 플래그를 유지한다(정렬은 동일 계약 기준이지만 UI에서 N-tier를 최하단으로 배치).
- `GET /api/ops/2026-online-retention`: 상태=Won, 생성일 ≥ 2024-01-01, 과정포맷이 온라인 3종(구독제/선택구매/포팅), 금액·수강시작일·수강종료일·코스ID가 모두 존재하는 딜만 반환한다(수강종료일 2024-10~2027-12 범위 권장). people/organization을 조인해 `orgId/orgName/upperOrg/teamSignature/personId/personName/createdAt/dealName/courseFormat/status/amount/onlineCycle/onlineFirst/startDate/endDate/owners/memoCount` 필드를 내려주며, owners는 deal.owner_json 우선→people.owner_json 보조로 파싱한다. 정렬은 endDate asc → orgName asc → dealId asc, meta에 db_version/rowCount를 포함한다.
- `GET /api/rank/2025-top100-counterparty-dri/targets-summary?size=대기업` → 규모별 DRI 행을 받아 티어 그룹별 target26/coverage/expected 합계와 DB snapshot 정보를 제공한다(프런트 Target Board 계산에 사용).
- `GET /api/rank/2025-counterparty-dri/detail?orgId=...&upperOrg=...`: 해당 org/upper_org 딜 상세, `deals[]`에 `people_id/people_name/upper_org` 포함.
- 프런트 랭킹 화면은 `/api/rank/2025-deals`만 사용해 26년 타겟(온라인/비온라인)을 클라이언트에서 계산하며, summary-by-size 응답은 UI에서 직접 사용하지 않는다.

## Invariants (Must Not Break)
- ONLINE 포맷은 정확히 `구독제(온라인)`, `선택구매(온라인)`, `포팅`만 인정한다(`statepath_engine.ONLINE_COURSE_FORMATS`).
- `/rank/2025-deals` 등 Won 기반 집계는 계약연도 2025만 포함하며 상태가 Won이 아닌 딜은 제외된다.
- `/rank/2025-deals-people`는 상위 조직/팀이 모두 미입력인 행을 제외하고 won2025 desc 정렬을 유지한다.
- 카운터파티 DRI는 Lost/Convert 제외, 확정/높음/Won만 포함하며 owners는 People.owner_json을 우선 사용한다(`tests/test_api_counterparty_dri.py`). target26 필드는 API에서 제공되면 override 플래그를 함께 내려야 하고, 없으면 프런트가 티어별 multiplier로 계산한다.
- summary-by-size는 exclude_org_name 기본값 “삼성전자”이며 snapshot_version이 DB mtime을 포함해야 한다.

## Coupling Map
- 라우터/집계: `dashboard/server/org_tables_api.py` ↔ `dashboard/server/database.py`(get_rank_* 함수들).
- 프런트: `org_tables_v2.html`의 랭킹/카운터파티/이상치 화면(fetchRankData, renderRankCounterpartyDriScreen 등).
- 테스트: `tests/test_api_counterparty_dri.py`(owners/온라인/정렬/limit/offset/배제), 기타 랭킹 관련 테스트는 없지만 프런트 스냅샷이 의존한다.

## Edge Cases & Failure Modes
- size 파라미터에 없는 값이 들어오면 필터가 적용되지 않아 전체를 반환한다.
- cpOffline/Online 2026 집계는 2025 딜이라도 start_date 연도가 2026이면 2026 합계에 포함된다.
- owners JSON이 비어 있으면 owners2025가 빈 배열이 되어 DRI 필터에서 제외될 수 있다.
- summary-by-size 캐시가 프로세스 메모리에 남아 DB 교체 후에도 이전 snapshot_version을 반환할 수 있다.

## Verification
- `/api/rank/2025-deals`가 Won 2025만 포함하고 totalAmount desc 정렬인지 샘플 DB로 확인한다.
- `/api/rank/2025-deals-people`가 상위 조직/팀 미입력만인 행을 제외하고 won2025 desc 정렬인지 확인한다.
- `/api/rank/mismatched-deals`가 orgId≠peopleOrgId 행만 반환하는지 확인한다.
- `/api/rank/2025-top100-counterparty-dri`가 Lost/Convert 제외, 온라인 판정/owners 우선순위, orgWon2025 desc→cpTotal2025 desc 정렬을 유지하는지 테스트 케이스와 대조한다.
- `/api/rank/2025-counterparty-dri/detail`에서 deals[].people_id/people_name/upper_org가 존재해 프런트 팝업에 상위 조직/교담자 컬럼을 채우는지 확인한다.
- `/api/rank/2025/summary-by-size` 응답에 snapshot_version=db_mtime:*이 포함되고 exclude_org_names에 삼성전자가 기본 포함되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 랭킹/DRI/이상치/요약 집계가 모두 `database.py` 하나에 모여 있고, 캐시 키가 DB mtime 기반으로 프로세스 재시작이 필요하다.
- ONLINE 판정 상수가 statepath_engine와 database에 중복돼 있어 변경 시 동기화가 필요하다.
- owners 추출 우선순위(people→deal)가 프런트 DRI 필터링과 연관되어 있어 소스 변경 시 UI 계약이 깨질 수 있다.
