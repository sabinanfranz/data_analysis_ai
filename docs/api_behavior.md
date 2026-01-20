---
title: API Behavior Notes (dashboard/server)
last_synced: 2026-01-12
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - dashboard/server/statepath_engine.py
  - dashboard/server/report_scheduler.py
  - tests/test_perf_monthly_contracts.py
  - tests/test_pl_progress_2026.py
  - tests/test_api_counterparty_dri.py
---

## Purpose
- FastAPI 라우터(`dashboard/server/org_tables_api.py`)와 DB 레이어(`dashboard/server/database.py`)의 실제 동작·정렬·캐시 규칙을 최신 코드 기준으로 기록한다.

## Behavioral Contract
- **공통**: DB 경로는 `DB_PATH`(기본 `salesmap_latest.db`); 존재하지 않으면 대부분 500을 반환한다. `/api/health`는 항상 `{"status": "ok"}`.
- **조직/기본 데이터**: `/api/sizes`는 organization의 유효한 규모를 알파벳 오름차순으로 반환하며 프런트가 `"전체"`를 prepend한다. `/api/orgs`는 People 또는 Deal이 1건 이상 연결된 조직만, 2025 Won 합계 desc→이름 asc 정렬, limit 기본 200(상한 500). `/api/orgs/{id}`는 미존재 시 404. 메모/People/Deal 조회(`/orgs/{id}/memos`, `/people/{id}/deals`, `/people/{id}/memos`, `/deals/{id}/memos`)는 createdAt desc, limit 상한 500. `/api/initial-data`는 조직/People/Deal/메모 전량을 로딩해 People(딜 있음/없음) 분리 후 반환한다.
- **Won JSON**: `/api/orgs/{orgId}/won-groups-json`은 23/24/25 Won 딜이 있는 상위 조직만 그룹에 포함한다. organization 블록에 `industry_major/mid`를 포함하며, People 웹폼은 `{name, date}`로 변환해 id는 숨긴다(기록 없으면 `"날짜 확인 불가"`, 동일 id 다중 제출은 날짜 리스트). 폼 메모는 `_clean_form_memo` 규칙(utm_source 또는 “고객 마케팅 수신 동의” 트리거, 전화/규모/업종/채널/동의/utm 키 드롭, 정보 부족/특수 문구 시 제외)으로 `cleanText`에 넣고, 실패 시 원문 `text`를 둔다. `/won-groups-json-compact`는 schema_version=`won-groups-json/compact-v1`, deal_defaults(>=80% 반복 필드) 추출, Won 딜 요약(`won_amount_by_year` 등) 합산까지 동일하게 수행하며 memos/webforms는 유지하되 **`htmlBody` 필드는 API 단계에서 제거된다**(compact는 텍스트 중심 JSON).
- **StatePath**: `/api/orgs/{orgId}/statepath`는 compact JSON을 입력으로 `statepath_engine.build_statepath` 결과(2024/2025 상태, Path 이벤트, Seed, 추천, 금액은 이미 억 단위)를 `{"item": ...}`로 제공한다. `/api/statepath/portfolio-2425`는 Won 딜을 org×lane×rail(온라인/비온라인)로 집계 후 bucket/이벤트/전이 매트릭스/seed/rail 변화 요약과 리스트를 반환하며, segment/search/정렬/패턴/리스크 필터(위험/OPEN/ScaleUp/회사 전이/셀 이벤트/rail 전이 등)와 limit/offset을 Query로 받는다. `/api/orgs/{orgId}/statepath-2425`는 단건 버전으로 동일 집계 규칙을 적용한다.
- **사업부 퍼포먼스**: `/api/performance/monthly-amounts/summary`는 2025-01~2026-12 월 키(YYMM) 24개 모두 포함하고 세그먼트 11종(label: 기업 고객/공공/온라인/비온라인/삼성 등)마다 row를 `TOTAL→CONTRACT→CONFIRMED→HIGH` 순으로 반환한다. 금액은 원 단위, TOTAL은 나머지 3버킷 합계다. `team=edu1|edu2` 파라미터를 주면 day1OwnerNames가 해당 팀 구성원인 딜만 필터링한다. `/api/performance/monthly-amounts/deals`는 row=TOTAL일 때 CONTRACT/CONFIRMED/HIGH 합집합을 dedupe 후 반환하며 `totalAmount`는 amount>0 else expected_amount 합산이다(동일하게 `team` 필터 지원). `/api/performance/pl-progress-2026/summary`는 Target(T) 컬럼에 `PL_2026_TARGET`을, Expected(E) 컬럼에 `recognized_by_month`(금액/예상액을 기간 비율로 분배해 억 단위) 합산값을 채운다. `OP_MARGIN`은 연간 OP/REV로 계산되며 월별 E 열만 드릴다운 가능하다. `/api/performance/pl-progress-2026/deals`는 E 변형만 지원하며, 선택 월/rail(TOTAL|ONLINE|OFFLINE) 기준 recognizedAmount desc→amountUsed desc→dealName desc 정렬로 반환한다.
- **랭킹/카운터파티**: `/api/rank/2025-deals`, `/api/rank/2025-deals-people`, `/api/rank/mismatched-deals`, `/api/rank/won-yearly-totals`, `/api/rank/won-industry-summary`는 DB 조회 결과 그대로 전달한다. `/api/rank/2025/summary-by-size`는 Won 딜을 계약연도 기준으로 규모별 합산하고 `snapshot_version=db_mtime:<int>` 캐시 키를 포함한다. `/api/rank/2025-top100-counterparty-dri`는 Lost/Convert 제외, 2025/2026 계약/예상일이 있는 Won·확정·높음 딜을 orgWon2025 desc→cpTotal2025 desc 정렬로 **규모별 전체 반환**하며 limit/offset은 선택 사항이다(기본 전체). 온라인 판정은 `statepath_engine.ONLINE_COURSE_FORMATS`, owners는 People.owner_json이 있으면 우선하며 target26 필드가 있으면 override 여부(`target26OfflineIsOverride/target26OnlineIsOverride`)를 함께 내려준다. `/api/rank/2025-top100-counterparty-dri/targets-summary`는 규모별 target/coverage/expected 합계와 snapshot_version/targets_version을 제공한다. `/api/rank/2025-counterparty-dri/detail`은 orgId+upperOrg별 딜 상세를 반환하며 사람/상위 조직 필드를 그대로 포함한다.
- **딜체크/QC**: `/api/deal-check?team=edu1|edu2`는 `PART_STRUCTURE`에 속한 담당자가 포함된 `상태='SQL'` 딜만 반환하고 orgWon2025Total desc→createdAt asc→dealId asc 정렬한다. isRetention은 2025 Won 금액 파싱 성공 여부로 판단하며 예상 체결액은 사용하지 않는다. `/api/qc/deal-errors/summary|person`는 QC_RULES(R1~R16) 위배 건수를 팀별/담당자별로 계산해 반환한다. R13은 상태가 convert가 아니고 규모가 대기업/중견기업인 딜에서만 상위조직/팀/직급/교육영역 결측 여부를 검사한다(기존 예외/조건 동일). 라벨: “고객사 담당자 정보 결측”. R16은 2025-01-01 이후 생성·비온라인·카테고리=생성형AI·규모=대기업·상태=Won 딜에서 제안서 작성/업로드 여부를 검사한다(작성 공백 또는 작성≠X인데 업로드 공백이면 위배).
- **카운터파티 리스크 리포트**: `/api/report/counterparty-risk`는 캐시(`report_cache/YYYY-MM-DD.json`)가 없으면 `report_scheduler.run_daily_counterparty_risk_job`을 실행해 생성 후 반환하며, summary(`tier_groups`, `counts`), `counterparties[]`(`target_2026/coverage_2026/expected_2026/gap/coverage_ratio/pipeline_zero/tier/evidence_bullets/recommended_actions`), `data_quality`, `meta.db_version`를 포함한다. DB가 최근 수정 중이면 `DB_STABLE_WINDOW_SEC` 안에서는 실패로 기록하고 status.json에 남긴다. `/api/report/counterparty-risk/status`는 status.json 내용을 그대로 반환한다. `/api/report/counterparty-risk/recompute`는 date 유효성 검사 후 강제 재계산한다.

## Invariants (Must Not Break)
- DB 존재 여부를 모든 조회가 전제로 하며, 경로는 `DB_PATH` 환경 변수로만 제어된다(`database.py`).
- `/api/orgs` 정렬은 won2025 desc→name asc 고정이고 People/Deal가 모두 0이면 제외된다(`database.list_organizations`).
- `won-groups-json` 그룹은 23/24/25 Won 딜 upper_org만 포함하며 webform id는 절대 노출하지 않는다(`database.get_won_groups_json`).
- 폼 메모 정제는 utm_source 또는 “고객 마케팅 수신 동의”가 없는 경우 스킵하며, 전화/규모/업종/채널/동의/utm 키는 항상 제거된다(`database._clean_form_memo`). 정제가 비어 있으면 메모를 제외한다.
- 월별 체결액 요약은 months 24개와 row 순서 TOTAL→CONTRACT→CONFIRMED→HIGH가 보장되고 segment key/label은 `_perf_segments` 정의에만 따른다(`database.get_perf_monthly_amounts_summary`).
- P&L 진행율매출 요약은 Target=T, Expected=E 두 variant를 모두 포함하고, E는 `recognized_by_month`를 억 단위 소수 4자리로 반영한다(`database.get_pl_progress_summary`). T 변형 드릴다운은 항상 빈 리스트를 반환한다.
- 카운터파티 DRI는 Lost/Convert를 제외하고, prob 높음/확정 또는 Won 상태가 아닌 딜은 cpTotal2025에 포함되지 않는다(`database.get_rank_2025_top100_counterparty_dri`; `tests/test_api_counterparty_dri.py`). owners는 People.owner_json을 우선 사용하고 deal.owner_json은 보조로만 쓴다. target26 override 값이 있으면 `target26*IsOverride` 플래그가 함께 내려가야 한다(`database.load_counterparty_targets_2026`).
- `/api/deal-check` 응답 정렬(OrgWon2025 desc→createdAt asc→dealId asc)과 memoCount left join 규칙은 고정이다(`database.get_deal_check`).
- Counterparty Risk 리포트는 summary.tier_groups가 S0/P0/P1, P2 그룹을 모두 포함해야 하며 counterparties 목록에는 coverage_ratio/gap/pipeline_zero가 포함된다. `meta.db_version`과 data_quality 플래그는 항상 존재해야 한다.

## Coupling Map
- 프런트: `org_tables_v2.html` fetch wrapper가 모든 `/api/*`를 사용하며, Won JSON/StatePath/카운터파티/월별 체결액/딜체크 화면의 캐시·모달 렌더링을 담당한다.
- 백엔드 라우터: `org_tables_api.py`가 FastAPI 라우트 정의, `report_scheduler.py`가 카운터파티 리포트 캐시/락 관리.
- 로직/데이터: `database.py`가 모든 집계·정렬·캐시를 담당하며, JSON 축약은 `json_compact.py`, StatePath 계산은 `statepath_engine.py`를 호출한다.
- 테스트: `tests/test_perf_monthly_contracts.py`, `tests/test_pl_progress_2026.py`, `tests/test_api_counterparty_dri.py`가 월별 체결액/P&L/DRI 계약을 검증한다.

## Edge Cases & Failure Modes
- DB 없거나 수정 중이면 FileNotFoundError→HTTP 500, 카운터파티 리포트는 status.json에 `DB_UNSTABLE_OR_UPDATING` 기록 후 실패한다.
- `/api/rank/2025/summary-by-size` 등 캐시 키는 DB mtime 포함; DB 교체 후에도 FastAPI 프로세스를 재시작하지 않으면 이전 캐시가 남을 수 있다.
- `/api/performance/*`는 잘못된 month(YYMM)나 segment/row 키 요청 시 400을 반환한다.
- `/api/report/counterparty-risk`는 date 파라미터 파싱 실패 시 400을 반환하며, lock 파일(`report_cache/.counterparty_risk.lock`)을 잡지 못하면 실행이 누락된다.
- compact 변환은 memos/webforms를 제거하지 않고 그대로 남기므로 개인정보 제거 용도로 사용할 수 없다.
- Counterparty DRI target/summary는 target 파일이 없거나 targets_version이 바뀌면 override 플래그/합계가 비어 있을 수 있으며, snapshot_version은 DB mtime과 targets_version 조합에 따라 달라진다.
- Counterparty Risk는 LLM/캐시 생성 중 DB 변경·락 실패로 status.json만 갱신되고 응답이 500/400으로 끝날 수 있다.

## Verification
- DB 없는 상태에서 `/api/orgs` 호출 시 500이 나는지, DB 생성 후 정상 응답하는지 확인한다.
- `/api/orgs`가 won2025 desc→name asc 순으로 정렬되고 People/Deal 0건 조직이 제외되는지 샘플 DB로 확인한다.
- `/api/orgs/{id}/won-groups-json`에서 industry_major/mid와 webforms `{name, date}` 매핑, 폼 메모 정제/제외 규칙이 적용되는지 확인한다.
- `/api/performance/monthly-amounts/summary`가 24개월 키와 row 순서, 세그먼트 label을 포함하고 `/performance/monthly-amounts/deals`의 row=TOTAL이 3버킷 합집합이며 totalAmount가 amount>0 else expected_amount 합산인지 샘플 월로 검증한다. `team=edu1|edu2` 적용 시 day1OwnerNames가 해당 팀 구성원에 속하는 딜만 남는지 확인한다.
- `/api/performance/pl-progress-2026/summary`가 T/E 컬럼을 모두 포함하고 current month E 셀 클릭 시 `/performance/pl-progress-2026/deals`가 recognizedAmount desc→amountUsed desc→dealName desc 정렬로 반환되는지 확인한다.
- `/api/rank/2025-top100-counterparty-dri`가 Lost/Convert 제외, orgWon2025 desc→cpTotal2025 desc 정렬을 유지하고 owners를 People.owner_json 우선으로 채우는지 테스트 케이스와 대조한다. target26 필드가 override 플래그와 함께 내려오는지, `/rank/2025-top100-counterparty-dri/targets-summary`가 snapshot_version/targets_version과 합계를 포함하는지 확인한다.
- `/api/deal-check?team=edu1|edu2` 결과에 memoCount/personId/personName/orgWon2025Total이 포함되고 정렬이 orgWon2025 desc→createdAt asc→dealId asc인지 확인한다.
- `/api/statepath/portfolio-2425`가 segment/search/정렬/필터 파라미터를 모두 반영해 bucket/전이/rail/seed 요약과 items를 반환하는지 확인한다.
- `/api/report/counterparty-risk`가 summary/counts/data_quality/meta.db_version과 counterparties 필드를 포함하고 캐시 미존재 시 생성 후 반환되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 여러 엔드포인트가 DB mtime 기반 메모리 캐시(`_COUNTERPARTY_DRI_CACHE`, `_PERF_MONTHLY_*`, `_PL_PROGRESS_*`, `_RANK_2025_SUMMARY_CACHE`)를 사용해 프로세스 재시작 없이는 최신 DB를 자동 반영하지 않는다.
- 온라인 판정 상수는 `statepath_engine.ONLINE_COURSE_FORMATS`와 `database.ONLINE_PNL_FORMATS`/`ONLINE_COURSE_FORMATS` 등 파일별로 중복 정의돼 있어 변경 시 동기화가 필요하다.
- deal-check/QC/DRI/StatePath 등 다수 엔드포인트가 `database.py` 단일 파일에 집중돼 있어 함수 분리 없이 수정 시 충돌 가능성이 높다.
