---
title: Daily Progress Log
last_synced: 2026-01-06
sync_source:
  - org_tables_v2.html
  - build_org_tables.py
  - salesmap_first_page_snapshot.py
  - dashboard/server/database.py
  - dashboard/server/org_tables_api.py
---

## Purpose
- 주요 기능 추가·수정 내역을 일자별로 기록해 추후 원인 추적과 리팩토링 계획에 참고한다.

## Behavioral Contract
- N/A (이 문서는 실행 동작 계약이 아닌 변경 기록이며, 실제 동작은 각 기능 문서를 참고한다.)

## Invariants (Must Not Break)
- 기록은 일자별로 구분되며, 언급된 파일/엔드포인트는 실제 코드에 존재해야 한다.
- 동일 내용이 여러 문서에 반영되었다고 적힌 경우, 각 문서(`docs/org_tables_v2.md`, `docs/api_behavior.md`, 등)가 같은 사실을 담고 있어야 한다.

## Coupling Map
- 변경 근거: `org_tables_v2.html`, `dashboard/server/database.py`, `dashboard/server/org_tables_api.py`, `build_org_tables.py`, `salesmap_first_page_snapshot.py` 및 해당 테스트(`tests/*`).
- 문서 반영: UI/UX 변경은 `docs/org_tables_v2.md`, API 계약은 `docs/api_behavior.md`, 스냅샷/파이프라인은 `docs/snapshot_pipeline.md`에 동기화된다.

## Edge Cases & Failure Modes
- N/A (변경 기록 전용 문서).

## Verification
- 기록된 날짜의 변경 사항이 git diff/테스트/문서에 실제 반영되어 있는지 spot-check한다.
- 언급된 테스트(`tests/test_pl_progress_2026.py`, `tests/test_perf_monthly_contracts.py` 등)가 해당 시점에 통과하는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- **2025-12-11**: org_tables_v2 메뉴 확장 및 상위 조직 JSON UX 개선(단일 카드/모달, 전체 리셋 시 검색·규모 초기화). `/api/rank/2025-deals-people`, `/api/rank/mismatched-deals` 추가. webform submit 수집 도구(`analyze_sequence_ids.py`)와 webform_history 후처리 추가. 문서/프런트 테스트 갱신.
- **2025-12-14**: compact JSON 엔드포인트(`/orgs/{id}/won-groups-json-compact`) 추가 및 프런트 버튼 연결; 랭킹 UI에 등급/배수/목표 모달 추가; 메모/웹폼 정제 규칙 확장(“고객 마케팅 수신 동의” 포함, ATD/SkyHive/제3자 동의 드롭). webform_history 적재 시 허용 ID 필터링 추가.
- **2025-12-15**: StatePath 엔진(`statepath_engine.py`)과 `/api/orgs/{id}/statepath` 추가, org_tables_v2에 StatePath 모달 및 owners2025 컬럼 반영. 테스트 추가.
- **2025-12-24**: PowerShell 실행 가이드 업데이트, 스냅샷 rename/체크포인트 폴백 로직 강화(`replace_file_with_retry`, `CheckpointManager.save_table`). 문서(`docs/user_guide.md`, `docs/snapshot_pipeline.md`) 최신화.
- **2026-01-06**: 2026 P&L/월별 체결액 화면 고도화(T/E 열, current month 하이라이트, assumption bar, deals 모달), `/performance/*` API 및 테스트(`test_pl_progress_2026.py`, `test_perf_monthly_contracts.py`) 정렬/집계 보강. 2026 카운터파티 DRI 화면/필터 정렬 개선(`renderRankCounterpartyDriScreen`, `/rank/2025-top100-counterparty-dri` 캐시 사용).
