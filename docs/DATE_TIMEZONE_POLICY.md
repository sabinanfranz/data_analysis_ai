---
title: Date/Timezone Policy (KST SSOT)
last_synced: 2026-01-28
sync_source:
  - dashboard/server/date_kst.py
  - org_tables_v2.html
  - tests/test_no_raw_date_ops.py
---

## Purpose
- 시스템의 날짜/타임존 처리를 KST(Asia/Seoul) 기준 date-only로 일원화하기 위한 운영/개발 가이드(과도기 포함).

## Policy (Current Transitional Stage)
- 최종 목표: 백엔드가 모든 날짜를 KST 기준 `YYYY-MM-DD`로 확정해 내려주고, 프런트는 그대로 표시한다.
- 과도기 대응: ISO datetime(Z/offset)을 프런트에서 표시할 때 `formatDateKstSafe`로 KST 변환해 안전하게 노출한다. date-only 응답은 그대로 사용한다.
- 금지 방향: raw 문자열 슬라이스/`split("T")`/`LIKE '202'`/`SUBSTR(...)` 기반 연·월 판정은 제거 대상. PR5에서는 탐지(비차단)만 추가한다.
- 모드: DATE_KST_MODE=legacy/shadow/strict
  - legacy(기본): 기존 동작 유지
  - shadow: 응답은 legacy 그대로, strict 계산을 로그로만 비교(backend)
  - strict: SSOT(date_kst) 기반으로 연/월/날짜 판정 적용(향후 단계)

## Frontend Guard Rails
- 새 포맷터 `formatDateKstSafe`는 ISO+TZ 문자열이면 KST로 포맷, date-only는 그대로 반환한다.
- `formatDateYYMMDDKstSafe`는 KST 포맷 결과를 YY.MM.DD로 변환.
- 기존 `formatDate`는 유지하되, 리스크 높은 화면부터 KST-safe 포맷터로 교체한다.

## Backend Guard Rails (플랜)
- `date_kst` 모듈만 날짜 정규화를 담당하며, SQL에서는 `kst_date/kst_year/kst_ym/kst_yymm` UDF만 사용하게 전환한다(legacy/shadow는 기존 SQL 유지).
- raw split/LIKE/SUBSTR 기반 연·월 판정을 제거하기 위해 코드베이스 전역을 점진 교체한다.

## Detection / QA
- `tests/test_no_raw_date_ops.py`가 raw split("T")/LIKE '202'/SUBSTR 패턴을 스캔한다. 기본은 비차단, `RAW_DATE_OPS_ENFORCE=1` 설정 시 실패로 전환 가능.
- 프런트는 DevTools/샘플 데이터로 ISO Z(예: 2025-12-31T15:00:00Z) 표시가 KST 익일로 보이는지 수동 확인한다.

## Rollout / Rollback
- 롤아웃: legacy → shadow(로그 수집) → strict(실동작) 순으로 점진 전환.
- 롤백: DATE_KST_MODE=legacy 로 즉시 복구.
