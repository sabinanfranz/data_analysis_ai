---
title: 핵심 조회 API 계약 (org_tables_v2.html 사용)
last_synced: 2026-01-06
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
  - `GET /api/orgs/{id}/won-groups-json-compact` → schema_version `won-groups-json/compact-v1`, deal_defaults(>=80% 반복 필드) 추출, Won 요약(summary) 누적. **현재 구현은 memos/webforms를 compact 결과에 그대로 보존**한다.
  - `GET /api/orgs/{id}/won-summary` → 상위 조직별 Won 합계(2023/2024/2025) + owners/owners2025/dealCount.
- 랭킹/DRI/StatePath:
  - `GET /api/rank/2025/summary-by-size?exclude_org_name=삼성전자&years=2025,2026` → Won 합계 규모별, 캐시 키 `snapshot_version=db_mtime:<int>`.
  - `GET /api/rank/2025-deals`, `/api/rank/2025-deals-people`, `/api/rank/mismatched-deals`, `/api/rank/won-yearly-totals`, `/api/rank/won-industry-summary` → DB 조회 결과 그대로 반환.
  - `GET /api/rank/2025-top100-counterparty-dri?size=대기업` → Lost/Convert 제외, 2025/2026 계약/예상 딜 중 확정/높음/Won만 집계, orgWon2025 desc→cpTotal2025 desc 정렬, owners는 People.owner_json 우선. 기본은 규모별 **전체** 반환이며 limit/offset은 선택 사항.
  - `GET /api/rank/2025-counterparty-dri/detail?orgId=...&upperOrg=...` → 해당 org/upper_org 딜 상세(people_id/people_name/upper_org 포함).
  - `GET /api/statepath/portfolio-2425` → segment/search/정렬/패턴/리스크 필터 반영된 요약+아이템(금액은 억 단위). `GET /api/orgs/{id}/statepath-2425`는 단건 버전.
  - `GET /api/orgs/{id}/statepath` → compact JSON 기반 statepath_engine 결과(2024/2025 상태·Path·추천, 금액은 억 단위) 반환.
- 사업부 퍼포먼스:
  - `GET /api/performance/monthly-amounts/summary?from=2025-01&to=2026-12` → months=YYMM 24개, segment 11종, rows=TOTAL→CONTRACT→CONFIRMED→HIGH. 금액 원 단위, TOTAL은 나머지 합. snapshot_version 포함.
  - `GET /api/performance/monthly-amounts/deals?segment=...&row=TOTAL|CONTRACT|CONFIRMED|HIGH&month=YYMM` → row=TOTAL은 3버킷 합집합 dedupe, totalAmount=amount>0 else expectedAmount 합산, items 정렬은 프런트가 수행.
  - `GET /api/performance/pl-progress-2026/summary` → Target(T) 열은 `PL_2026_TARGET`, Expected(E)는 기간 비율로 분배한 recognized_by_month 합계(억 단위 소수 4자리). OP_MARGIN은 연간 OP/REV. 캐시 키 `_PL_PROGRESS_SUMMARY_CACHE`.
  - `GET /api/performance/pl-progress-2026/deals?year=2026&month=YYMM&rail=TOTAL|ONLINE|OFFLINE&variant=E` → recognizedAmount desc→amountUsed desc→dealName desc 정렬. variant T는 빈 리스트 반환.
- 딜체크/QC:
  - `GET /api/deal-check?team=edu1|edu2` → `상태='SQL'` 딜 중 팀 구성원 포함 건만, orgWon2025Total desc→createdAt asc→dealId asc, memoCount join. isRetention은 2025 Won 금액 파싱 성공 여부.
  - `GET /api/deal-check/edu1|edu2` → 위 래퍼.
  - `GET /api/qc/deal-errors/summary?team=all|edu1|edu2|public` → QC_RULES(R1~R15) 위배 수 집계. `GET /api/qc/deal-errors/person?owner=...&team=...` → 담당자별 위배 리스트.
- 카운터파티 리스크:
  - `GET /api/report/counterparty-risk?date=YYYY-MM-DD` → 캐시 없으면 `report_scheduler.run_daily_counterparty_risk_job` 실행 후 반환. `POST /api/report/counterparty-risk/recompute`는 강제 재계산, `GET /api/report/counterparty-risk/status`는 status.json 반환.

## Invariants (Must Not Break)
- `/api/orgs` 정렬: won2025 desc → name asc, People/Deal 둘 다 0이면 제외.
- Won JSON 그룹: 2023/2024/2025 Won upper_org만 포함, webform id 미노출, webform 날짜는 `"날짜 확인 불가"`/단일/리스트 형태.
- 월별 체결액: months 24개, rows TOTAL→CONTRACT→CONFIRMED→HIGH 고정, segment label은 `_perf_segments` 정의(삼성/기업/공공/온라인/비온라인) 그대로 반환.
- P&L: columns 연간(T/E) → 월별(T/E) 순, Expected만 드릴다운 지원, Target 값은 `PL_2026_TARGET` 딕셔너리 그대로 사용.
- DRI: Lost/Convert 제외, prob 확정/높음/Won만 카운터파티 합산, owners는 People.owner_json을 우선 사용한다.
- 딜체크: memoCount left join, isRetention은 2025 Won 금액 파싱 성공 기준(예상 체결액 미사용).
- 캐시 키: DB mtime을 포함하는 메모리 캐시(`_COUNTERPARTY_DRI_CACHE`, `_PERF_MONTHLY_*`, `_PL_PROGRESS_*`, `_RANK_2025_SUMMARY_CACHE`)가 있어 프로세스 재시작 전까지 새 DB가 반영되지 않을 수 있다.

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

## Verification
- `/api/orgs`가 won2025 desc→name asc이고 People/Deal 0건 조직이 제외되는지 샘플 DB로 확인한다.
- `/api/orgs/{id}/won-groups-json`에 industry_major/mid, webforms `{name,date}`, cleanText 메모가 포함되고 upper_org가 Won 존재 조직만 있는지 확인한다.
- `/api/performance/monthly-amounts/summary`가 24개월·4개 row·11세그먼트를 포함하고 `/performance/monthly-amounts/deals` row=TOTAL이 3버킷 합집합인지 검증한다.
- `/api/performance/pl-progress-2026/summary`가 연간/월별 T/E 컬럼을 포함하고 current YYMM E 셀 클릭 시 `/performance/pl-progress-2026/deals`가 recognizedAmount desc→amountUsed desc→dealName desc 정렬인지 확인한다.
- `/api/rank/2025-top100-counterparty-dri`가 Lost/Convert 제외, orgWon2025 desc→cpTotal2025 desc 정렬이며 owners가 People.owner_json 우선으로 채워지는지 테스트 대비 확인한다.
- `/api/deal-check?team=edu1|edu2`가 orgWon2025 desc→createdAt asc→dealId asc 정렬이며 memoCount/personId/personName/orgWon2025Total을 포함하는지 확인한다.
- `/api/report/counterparty-risk` 호출 시 캐시 생성/재사용, status.json 업데이트가 정상인지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 캐시가 DB mtime 기반 메모리에만 존재해 프로세스 재시작 전까지 새 DB가 반영되지 않는다.
- 온라인 판정/PL_2026_TARGET 등 상수가 `database.py`와 프런트에 중복돼 있어 수정 시 양방향 반영이 필요하다.
- 딜체크/DRI/StatePath/월별/PL 등 다양한 기능이 모두 `database.py`에 집중되어 변경 영향 범위가 크다.
