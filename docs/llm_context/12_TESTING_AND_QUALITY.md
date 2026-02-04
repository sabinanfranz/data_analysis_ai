---
title: 테스트 & 품질 가이드
last_synced: 2026-02-04
sync_source:
  - tests/
  - org_tables_v2.html
  - dashboard/server/database.py
  - dashboard/server/org_tables_api.py
---

## Purpose
- 핵심 계약을 보호하는 테스트 세트와 실행 절차를 정리해 리팩토링 시 안전망을 제공한다.

## Behavioral Contract
- 실행 커맨드: `python -m unittest discover -s tests` (또는 `PYTHONPATH=. python -m unittest discover -s tests`). Node 테스트 없음(프런트 정적 HTML).
- 주요 테스트 커버리지 (파일 → 보호 계약):
  - `test_salesmap_first_page_snapshot.py`: 스냅샷 CLI 옵션/backup/rename/checkpoint/webform-only 동작.
  - `test_perf_monthly_contracts.py`: 월별 체결액 summary/deals row·segment·24개월 키·amount/expected 대체.
  - `test_perf_monthly_close_rate_summary.py`, `test_perf_monthly_close_rate_contract.py`: close-rate summary/deals scope/cust 필터, metric 분모/분자 규칙.
  - `test_perf_monthly_inquiries.py`, `test_perf_monthly_inquiries_online_first_filter.py`, `test_perf_monthly_inquiries_org_join.py`: 문의 인입 size×format×category 구조, online_first FALSE 제외 규칙, org join.
  - `test_pl_progress_2026.py`, `test_pl_progress_targets.py`: P&L Target/Expected, excluded 카운트, deals 정렬.
  - `test_api_counterparty_dri.py`: DRI 정렬(orgWon2025→cpTotal2025), ONLINE 판정, owners 우선순위, limit/offset, overrides.
  - `test_rank_2025_deals.py`, `test_rank_2025_deals_people.py`, `test_mismatched_deals_2025.py`, `test_won_totals_by_size.py`, `test_won_summary.py`: 랭킹/이상치/요약 정렬·필터.
  - `test_won_groups_json.py`, `test_compact_contract.py`, `test_markdown_compact.py`: 메모 cleanText/webform 날짜 매핑, compact/markdown schema_version, htmlBody 제거, deal_defaults 규칙.
  - `test_qc_r13_r17_hidden.py`, `test_qc_monthly_revenue_report.py`, `test_qc_since_filter.py`: QC 규칙(R1~R16, R17 숨김), 매출신고 xlsx, since 필터.
  - `test_deal_check_edu1.py`, `test_deal_check_recent_status.py`: deal-check 정렬, part 필터, recent window.
  - `test_statepath_engine.py`, `test_api_statepath_portfolio.py`: lane/rail bucket, path build, filters/sort/limit.
  - `test_date_kst.py`, `test_datetime_kst_normalization.py`, `test_no_raw_date_ops.py`: 날짜 파싱(KST 변환), raw date 미반환 보장.
  - `test_counterparty_*`(card_agent/llm/risk_rule/target/targets_loader): Counterparty 파이프라인 로직/모델/룰 검증.
  - `test_build_org_tables.py`, `test_build_org_mindmap.py`: 정적 HTML 빌더 CLI/데이터 포함 여부.
  - `org_tables_v2_frontend.test.js`: 프런트 JS 함수(loadOrgDetail, autoSelect, memo modal 정규화, JSON 버튼 enable/disable, StatePath export) 검증.

## Invariants (Must Not Break)
- 24개월 키(2501~2612)와 row 순서(TOTAL→CONTRACT→CONFIRMED→HIGH, close-rate metrics total→confirmed→high→low→lost→close_rate)는 고정.
- ONLINE 판정 집합, owners 우선순위(people.owner_json→deal.owner_json), DRI 정렬(orgWon2025 desc→cpTotal2025 desc) 불변.
- compact/markdown은 htmlBody 제거, phone 마스킹, memo_max_chars(기본 240), deal_memo_limit(기본 10) 적용.
- QC UI는 R1~R15만 노출, R17은 응답 issueCodes/byRule/totalIssues에서 제외.
- 스냅샷 테스트는 backup/checkpoint/rename/webform-only 동작을 전제로 한다.

## Coupling Map
- 테스트 → 코드: `dashboard/server/database.py`, `org_tables_api.py`, `json_compact.py`, `markdown_compact.py`, `statepath_engine.py`, `salesmap_first_page_snapshot.py`, `build_org_tables.py`, `org_tables_v2.html`(frontend JS).
- 테스트 → 문서: 본 문서와 05/06/07/08/09/10/11/13 계약을 보호한다.

## Edge Cases & Failure Modes
- 로컬 DB 스키마가 달라 테스트 생성 DB와 불일치하면 일부 테스트가 fallback 경로를 지나 실패/통과할 수 있다.
- `PYTHONPATH`를 설정하지 않으면 import 에러가 날 수 있음(Windows/venv 주의).
- 프런트 DOM/CSS 회귀는 JS 유닛 테스트가 없으므로 수동 확인 필요.

## Verification
- 전체: `PYTHONPATH=. python -m unittest discover -s tests` (또는 `python -m unittest discover -s tests`).
- 스냅샷: `python -m unittest tests/test_salesmap_first_page_snapshot.py`.
- 퍼포먼스: `python -m unittest tests/test_perf_monthly_contracts.py tests/test_perf_monthly_inquiries.py tests/test_perf_monthly_close_rate_summary.py`.
- P&L: `python -m unittest tests/test_pl_progress_2026.py tests/test_pl_progress_targets.py`.
- DRI/랭킹: `python -m unittest tests/test_api_counterparty_dri.py tests/test_rank_2025_deals.py`.
- compact/markdown: `python -m unittest tests/test_won_groups_json.py tests/test_compact_contract.py tests/test_markdown_compact.py`.
- 프런트 JS: `node --test tests/org_tables_v2_frontend.test.js` (JSDOM 기반, fetch stub 포함).

## Refactor-Planning Notes (Facts Only)
- 대규모 DB/성능/캐시 무효화는 단위 테스트에 포함되지 않으므로 별도 부하/통합 테스트가 필요하다.
- 프런트는 정적 HTML이라 시각적 회귀를 잡을 자동화가 없고, JS 유닛 테스트가 제한적이다.
- 날짜/시간 파싱 모드(DATE_KST_MODE)가 shadow/strict로 바뀌면 관련 테스트와 문서를 함께 갱신해야 한다.
