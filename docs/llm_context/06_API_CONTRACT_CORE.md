---
title: 핵심 조회 API 계약 (org_tables_v2.html 사용)
last_synced: 2026-02-04
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - dashboard/server/markdown_compact.py
  - org_tables_v2.html
  - tests/test_perf_monthly_contracts.py
  - tests/test_pl_progress_2026.py
  - tests/test_perf_monthly_inquiries_online_first_filter.py
  - tests/test_api_counterparty_dri.py
---

## Purpose
- org_tables_v2 프런트가 의존하는 FastAPI 핵심 엔드포인트의 파라미터, 기본값, 정렬, 응답 스키마, 캐시/필터 규칙을 코드 기준으로 명시한다.

## Behavioral Contract
### 공통
- DB_PATH 기본값 `salesmap_latest.db`; 파일 부재/잠금 시 500.
- 모든 금액/날짜는 TEXT 파싱 결과를 그대로 반환하며 클라이언트가 포맷팅한다.
- 서버 캐시는 모두 프로세스 메모리 기반이며 키에 DB mtime을 포함한다(재기동 필요 시점 명시는 Invariants 참조).

### 조직·메모·사람·딜
- `GET /api/sizes` → `{sizes:[...]} / ORDER BY size asc` (DB distinct). 프런트가 "전체"를 앞에 추가.
- `GET /api/orgs?size=전체&search&limit=200&offset=0`
  - limit 1–500 (기본 200), offset ≥0. size는 정확 일치 필터(전체는 무시), search는 이름/id LIKE.
  - people_count 또는 deal_count >0 조직만 반환. 정렬: won2025 DESC → name ASC.
  - 응답 `{items:[{id,name,size,team,owner}]}` team/owner는 JSON 파싱 결과 배열/객체.
- `GET /api/orgs/{id}` → 404 if not found. `{item:{id,name,size,team,owner}}`.
- `GET /api/orgs/{id}/people?hasDeal=true|false|null` → name ASC, deal_count join. hasDeal 필터가 true면 deal_count>0, false면 =0.
- `GET /api/orgs/{id}/memos?limit=100` (1–500) → org-only memos(createdAt DESC) with `ownerName` resolved.
- `GET /people/{id}/deals` → order by contract_date nulls last DESC, then created_at DESC; includes ownerName (deal."담당자" JSON name).
- `GET /people/{id}/memos?limit=200` / `GET /deals/{id}/memos?limit=200` → createdAt DESC; ownerName resolved; htmlBody 포함 여부는 memo 컬럼 존재 시 포함.

### Won JSON / Compact / Markdown
- `GET /api/orgs/{id}/won-summary` → upper_org 단위 Won 합계(2023/2024/2025) + contacts/owners/owners2025/dealCount, org_id 미존재 404.
- `GET /api/orgs/{id}/won-groups-json`
  - organization block: id/name/size/industry/industry_major/industry_mid + org memos.
  - groups: 2023/2024/2025 Won 딜이 존재하는 upper_org만 포함. 각 group.team은 people.team_signature(공백→"미입력").
  - people: id/name/upper_org/team_signature/title_signature/edu_area/webforms. webforms는 `{name,date}`로 id는 숨김; 날짜는 webform_history(peopleId/webFormId/createdAt) 매핑, 없으면 "날짜 확인 불가"(또는 리스트).
  - deals: 상태/금액/expected_amount/contract_date/start_date/end_date/probability/course_format/category/net_percent/owner/day1_team 등 원본 필드와 memos, people stub 포함. memos는 `_clean_form_memo` 후 cleanText 또는 raw text/htmlBody.
- `GET /api/orgs/{id}/won-groups-json-compact` → schema_version `won-groups-json/compact-v1`; deal_defaults(>=80% 모드 필드) 추출; memos/webforms 유지하되 `htmlBody` 제거; 사람은 people_id 참조로 단순화; Won summary 누적 포함.
- `GET /api/orgs/{id}/won-groups-markdown-compact`
  - Query: upper_org(opt), max_deals(1–500, default 200), max_people(1–500, default 60), deal_memo_limit(1–50, default 10), memo_max_chars(50–500, default 240), redact_phone(default true), max_output_chars(10k–1M, default 200k), format=text|json(default text).
  - 반환: text → `text/plain; charset=utf-8`, json → `{schema_version:"won-groups-json/compact-md-v1.1", markdown:"..."}`.

### StatePath
- `GET /api/statepath/portfolio-2425`
  - Query: segment(default "전체" or alias sizeGroup), search(opt), sort(default `won2025_desc`), limit(default 500, 1–2000), offset(default 0), filters riskOnly/hasOpen/hasScaleUp(bool, default False), companyDir/seed/rail/railDir/companyFrom/companyTo/cell/cellEvent(default "all").
  - 응답 `{items:[...], summary, meta{db_version,snapshot_version}}` with company/rail buckets (억 단위), pattern filters applied.
- `GET /api/orgs/{id}/statepath-2425` → 단건 동일 포맷, 404 if org missing.
- `GET /api/orgs/{id}/statepath` → compact won JSON → statepath_engine state/path/reco, `{item:{state_2024,state_2025,path,recommendations,...}}`.

### Performance (사업부 퍼포먼스)
- `GET /api/performance/monthly-amounts/summary?from=2025-01&to=2026-12&team=`
  - from/to inclusive; months list = YYMM 24개. rows: TOTAL, CONTRACT, CONFIRMED, HIGH. segments 11종 `_perf_segments` 정의 순서. 금액 원 단위, totalAmount는 row 합.
  - team 필터(edu1/edu2) → day1OwnerNames가 팀 구성원인 딜만 포함. 캐시 `_PERF_MONTHLY_SUMMARY_CACHE` (키: db mtime, range, team).
- `GET /api/performance/monthly-amounts/deals?segment=&row=&month=&team=`
  - month YYMM 필수. row=TOTAL이면 CONTRACT/CONFIRMED/HIGH 합집합 dedupe. amountUsed = 금액>0 ? 금액 : 예상 체결액. 팀 필터 동일. 응답 items는 서버 기준 필터 후 그대로 반환(정렬 없음), meta.note 포함.
- `GET /api/performance/monthly-inquiries/summary?from=2025-01&to=2026-12&team=&debug=false`
  - months 24개, rows = level1 (size×course_format) + level2 (size×course_format×category_group). course_format 13종 고정, category_group 7종(온라인/생성형AI/DT/직무별교육/스킬/기타/미기재). size_group 7종. status=Convert 제외.
  - 온라인 3포맷(구독제(온라인)/선택구매(온라인)/포팅)에서 `online_first`가 명시적 FALSE인 행만 제외; NULL/공백은 포함. 팀 필터 시 day1OwnerNames가 팀 구성원인지 검사. debug=true면 캐시 우회 및 제외 건수/샘플 포함.
- `GET /api/performance/monthly-inquiries/deals?segment=&row=&month=&team=&debug=false`
  - row는 `<course_format>||<category_group>` 또는 미제공 시 `__ALL__` 두 필터 모두 전체. month YYMM 필수. online_first FALSE 제외 규칙 동일(온라인 포맷만). 결과 items는 딜 중복 제거, meta.dedupedDealsCount 포함.
- `GET /api/performance/monthly-close-rate/summary?from=2025-01&to=2026-12&cust=all|new|existing&scope=all|corp_group|edu1|edu2|edu1_p1|edu1_p2|edu2_p1|edu2_p2|edu2_online`
  - months 24개(2501~2612). rows: level1(size×course_group 4종), level2 metrics 6종(total/confirmed/high/low/lost/close_rate). cust=existing 판정: 25xx는 2024 조직 리스트, 26xx는 2025 Won 리스트. scope는 `_perf_close_rate_scope_members`에서 owner_names 매칭.
  - meta.debug에 existing 리스트 경로/mtime/카운트 및 팀 필터 제외 건수 포함. 캐시 `_PERF_MONTHLY_CLOSE_RATE_SUMMARY_CACHE`.
- `GET /api/performance/monthly-close-rate/deals?segment=&row=&month=&cust=all|new|existing&scope=...&course=&metric=`
  - row 형식 `<course_group>||<metric>` 필수 또는 course+metric로 조합. month YYMM 필수. metric ∈ {total,confirmed,high,low,lost,close_rate}. metric=total|close_rate는 분모 전체 딜, 나머지는 해당 버킷만 포함. meta에 numerator/denominator/close_rate 포함.
- `GET /api/performance/pl-progress-2026/summary?year=2026`
  - columns: 연간 T/E + 월별 T/E(YYMM). Target(T)=`PL_2026_TARGET`; Expected(E)=recognized_by_month(억 단위, 소수 4). meta.excluded {missing_dates, missing_amount, invalid_date_range}. 캐시 `_PL_PROGRESS_SUMMARY_CACHE`.
- `GET /api/performance/pl-progress-2026/deals?year=2026&month=YYMM&rail=TOTAL|ONLINE|OFFLINE&variant=E&limit=500&offset=0`
  - variant T는 항상 빈 리스트. 정렬: recognizedAmount DESC → amountUsed DESC → dealName DESC. limit 1–2000.

### Deal Check / QC
- `GET /api/deal-check?team=edu1|edu2` (필수) → 상태 SQL/Won/Lost/LOST 딜 중 팀 소유자 포함. window: Won/Lost는 최근 10 영업일 내(계약/LOST/expected). 정렬 orgWon2025Total DESC → createdAt ASC → dealId ASC. 필드: memoCount, planningSheetLink(컬럼 없으면 null), isRetention(orgWon2025Total>0), owner_names, expectedAmount, course_format 등.
- `GET /api/deal-check/edu1` / `.../edu2` → 위 래퍼.
- QC
  - `GET /api/qc/deal-errors/summary?team=all|edu1|edu2|public`
  - `GET /api/qc/deal-errors/person?owner=&team=`
  - 룰: R1~R16 응답 포함, R17 계산하나 응답 숨김. R13: 규모 대/중견 & 상태 Won/SQL에서 상위조직/팀/직급/교육영역 결측 검사. R16: 2025-01-01 이후, 비온라인, 카테고리=생성형AI, 규모=대기업, 상태=Won → 제안서 작성/업로드 필드 검사.

### Ops / Counterparty
- `GET /api/ops/2026-online-retention` → Won 딜(2024-01-01 이후, 온라인 3포맷, start/end 필수, end 2024-10-01~2027-12-31) 리스트 + meta{db_version,rowCount}. amount<=0 또는 날짜 누락은 제외.
- 카운터파티 리스크
  - `GET /api/report/counterparty-risk?date=YYYY-MM-DD&mode=offline|online(default)` → 캐시 미존재 시 `run_daily_counterparty_risk_job` 수행 후 반환. summary(counts/tier_groups), counterparties rows, meta.db_version/data_quality.
  - `POST /api/report/counterparty-risk/recompute` 강제 재계산. `GET /api/report/counterparty-risk/status?mode=` → status.json 반환(전체/단일 모드).

### 기타
- `/api/health` → `{status:"ok"}`. `/api/initial-data` → DB 없으면 500, 정상 시 초기 렌더용 요약 데이터를 반환(프런트 내부 소비).
- LLM 파이프라인: `POST /api/llm/target-attainment`(payload size 검증 후 run_target_attainment 실행, debug/nocache/include_input Query), `POST /api/llm/daily-report-v2/pipeline?pipeline_id=&variant=offline|online&debug=false&nocache=false` → orchestrator 실행.

## Invariants (Must Not Break)
- `/api/orgs` 정렬: won2025 DESC → name ASC, people/deal 모두 0이면 제외.
- Won 그룹: 2023/2024/2025 Won upper_org만 포함, webform id 미노출, webform 날짜는 단일/리스트/"날짜 확인 불가" 중 하나.
- Performance months: 모든 요약/클로즈레이트/인입/PL은 24개월(2501–2612) 고정, row/metric/segment 순서 고정.
- 캐시: `_PERF_MONTHLY_*`, `_PERF_MONTHLY_CLOSE_RATE_CACHE/SUMMARY_CACHE`, `_PL_PROGRESS_*`, `_COUNTERPARTY_*` 등은 DB mtime 키를 포함하므로 DB 교체 후 FastAPI 재시작 전까지 이전 데이터가 남을 수 있다.
- online_first 필터: monthly-inquiries에서만 적용, 온라인 3포맷에 한해 값이 명시적 FALSE일 때만 제외한다.
- pl-progress deals: variant=E만 데이터, T는 항상 빈 리스트.

## Coupling Map
- 라우터: `dashboard/server/org_tables_api.py` → DB 로직 `dashboard/server/database.py` → 보조(`json_compact.py`, `markdown_compact.py`, `statepath_engine.py`, `report_scheduler.py`).
- 프런트: `org_tables_v2.html` fetch 래퍼가 모든 엔드포인트 호출, 메뉴/모달/캐시를 관리.
- 테스트: `tests/test_perf_monthly_contracts.py`, `tests/test_perf_monthly_close_rate_summary.py`, `tests/test_pl_progress_2026.py`, `tests/test_perf_monthly_inquiries.py`, `tests/test_perf_monthly_inquiries_online_first_filter.py`, `tests/test_api_counterparty_dri.py`, `tests/test_won_groups_json.py`, `tests/test_deal_check_edu1.py`, `tests/test_qc_r13_r17_hidden.py` 등이 계약을 보호한다.

## Edge Cases & Failure Modes
- DB 부재/잠금 → 500. 잘못된 파라미터(scope/segment/month 형식 등) → 400. compact/markdown max_output_chars 초과 시 서버에서 문자열을 자르고 `(truncated...)` 문구를 포함한다.
- 캐시가 살아있는 동안 DB 교체 시 오래된 snapshot_version 응답 가능; 운영 시 DB 교체 후 API 재기동 필요.
- webform_history 테이블/행이 없으면 webforms.date가 "날짜 확인 불가"로 채워지고 제출 리스트가 비어 있을 수 있다.
- monthly/close-rate/inquiries: 날짜/금액 파싱 실패 행은 제외되어 집계가 줄어들 수 있다.
- counterparty-risk: DB_STABLE_WINDOW_SEC 내 파일 변경 감지 시 실패를 status.json에 기록한다.

## Verification
- 목록/정렬: `curl -s "http://localhost:8000/api/orgs?limit=5" | jq '.items[0]'` → won2025 순 정렬 확인, people/deal 없는 조직이 제외됐는지 확인.
- Won JSON: `curl -s "http://localhost:8000/api/orgs/<org>/won-groups-json" | jq '.organization, .groups[0].people[0].webforms, .groups[0].deals[0].memos[0]'`
- 월별 체결액: `curl -s "http://localhost:8000/api/performance/monthly-amounts/summary?from=2025-01&to=2025-02" | jq '.months, .segments[0].rows[0].byMonth'`
- 월별 인입: `curl -s "http://localhost:8000/api/performance/monthly-inquiries/summary?from=2025-01&to=2025-01&team=edu2" | jq '.rows[0]'` → size/course/category 구조 확인, online_first 필터 동작 확인.
- 체결률: `curl -s "http://localhost:8000/api/performance/monthly-close-rate/summary?from=2025-01&to=2025-01" | jq '.rows | length'` (24*? 구조), deals 호출로 numerator/denominator 확인.
- PL: `curl -s "http://localhost:8000/api/performance/pl-progress-2026/summary" | jq '.columns[0], .meta.excluded'`; deals 클릭 시 `variant=E`만 응답하는지 확인.
- Deal-check: `curl -s "http://localhost:8000/api/deal-check/edu1" | jq '.items[0].planningSheetLink, .items[0].isRetention'`
- Counterparty-risk: `curl -s "http://localhost:8000/api/report/counterparty-risk" | jq '.meta.db_version, .summary.tier_groups'`

## Refactor-Planning Notes (Facts Only)
- 캐시/상수(ONLINE_COURSE_FORMATS, PL_2026_TARGET 등)가 프런트/백엔드에 중복 정의되어 동시 수정 필요.
- `_pick_column`/owner/team 매핑 로직이 여러 함수에 산재해 스키마 변경 시 영향 추적이 어렵다.
- DB mtime 기반 메모리 캐시 때문에 운영 DB 교체 후 API 재시작이 필요하며, 이를 자동화할 재로딩 훅이 없다.
