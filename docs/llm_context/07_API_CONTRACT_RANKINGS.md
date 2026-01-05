---
title: 랭킹/집계/이상치 API 계약
last_synced: 2025-12-24
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - org_tables_v2.html
---

# 랭킹/집계/이상치 API 계약

## 공통 규칙
- 금액 컬럼은 DB에 TEXT로 저장되며, 백엔드에서 `_to_number`로 변환 후 반환. 프런트는 억 단위(1e8)로 표시.
- 연도 필터는 `계약 체결일`에서 앞 4자리로 판단한다(없으면 생성일/수주예정일 등 각 엔드포인트 규칙을 따름).
- 규모(size) 필터가 있을 때만 적용(`전체`는 필터 없음).

## 엔드포인트별 정의

### GET `/api/rank/2025-deals`
- 집계 기준: `deal."상태"='Won'` AND `계약 체결일 LIKE '2025%'`.
- 필터: `size`(기업 규모, 옵션).
- 그룹: `organizationId`.
- 반환 필드:  
  - `orgId`, `orgName`(NULL 시 id), `industryMajor`, `industryMid`  
  - `totalAmount`(Won 금액 합계), `onlineAmount`, `offlineAmount`, `grade`(2025),  
    `totalAmount2024`, `grade2024`(2024 Won 총액 기준),  
    `formats`(과정포맷별 `{courseFormat,totalAmount}` 목록)
- 정렬: `totalAmount` 내림차순.

### GET `/api/rank/2025-deals-people`
- 목적: 2025 Won 딜이 있는 조직별 People 그룹 + 모든 딜(상태 무관) 목록.
- 필터: `size`(기업 규모, 옵션).
- 선별: 2025 Won 딜이 하나라도 있는 조직만 대상. 상위 조직/팀이 모두 `미입력`인 경우는 제외.
- 반환 필드(요소):  
  - `orgId`, `orgName`, `upper_org`, `team`, `personId`, `personName`, `title_signature`, `edu_area`, `won2025`(억 변환 전 금액 합), `dealCount`, `deals`(상태 무관 전체 딜: `created_at`, `name`, `status`, `amount`, `contract_date`, `course_format`)
- 정렬: `won2025` 내림차순.

### GET `/api/rank/mismatched-deals`
- 목적: 딜의 `organizationId`와 People의 `organizationId`가 다른 경우 탐지.
- 필터: `size`(딜 조직 기준, 옵션).
- 조건: `d.organizationId IS NOT NULL`, `p.organizationId IS NOT NULL`, `d.organizationId <> p.organizationId`.
- 반환 필드:  
  - `dealId`, `dealName`, `dealOrgId/Name`, `personId`, `personName`, `personOrgId/Name`, `contract_date`, `amount`, `course_format`, `course_shape`.
- 정렬: 없음(조회 순서 그대로).

### GET `/api/rank/won-yearly-totals`
- 집계 기준: `deal."상태"='Won'` AND `계약 체결일`이 2023/2024/2025.
- 그룹: 기업 규모(`o."기업 규모"` → 없으면 `미입력`).
- 반환 필드: `size`, `won2023/2024/2025`(해당 연도 Won 합계).
- 정렬: 전체 합계(won2023+won2024+won2025) 내림차순.

### GET `/api/rank/won-industry-summary`
- 집계 기준: `deal."상태"='Won'` AND `계약 체결일`이 2023/2024/2025.
- 필터: `size`(기업 규모, 기본 전체).
- 그룹: 업종 구분(대) + 조직 id. 업종 구분(대)가 NULL이면 `미입력`.
- 반환 필드(업종별): `industry`(업종 구분 대), `won2023/2024/2025` 합계, `orgCount`(조직 수).
- 정렬: 총액(won2023+won2024+won2025) 내림차순.

### GET `/api/rank/2025-top100-counterparty-dri`
- 목적: 규모별 2025 Won Top100 기업에 대해 상위 조직(upper_org)별 온라인/비온라인/담당자/DRI 계산.
- 필터: `size`(기본 `대기업`), `limit`(기본 100, 최대 200), `offset`(기본 0, org 목록 페이지네이션용).
- 집계 규칙:
  - 조건: 계약 연도(계약체결일 없으면 수주예정일) 2025/2026, 성사 가능성 `확정`/`높음`만 포함(문자열/리스트/JSON 문자열 모두 인식).
  - 온라인: `구독제(온라인)`, `선택구매(온라인)`, `포팅`(완전 일치), 그 외는 비온라인
  - upper_org가 없으면 `미입력`으로 그룹
  - owners2025: **People 테이블의 `담당자`** JSON에서 이름/ID를 우선 추출하고, 비어 있으면 deal `담당자`로 폴백. 두 소스 모두 없으면 `미입력`.
- 비온라인 합산:
  - `cpOffline2025`: 고확률(prob) 비온라인 + 연도=2025, 단 수강시작일 연도=2026인 딜은 제외
  - `cpOffline2026`: 고확률 비온라인 + 연도=2026, 그리고 고확률 비온라인 + 연도=2025이면서 수강시작일 연도=2026인 딜을 추가 가산
- 정렬: orgWon2025 desc → cpTotal2025 desc (cpTotal은 정렬용, 표시는 하지 않음)
- 반환 필드(행):
  - `orgId/orgName`, `orgTier`(grade), `orgWon2025` (orgOnline/offline는 필요 시만 활용)
  - `upperOrg`, `cpOnline2025`, `cpOffline2025`, `cpTotal2025`, `owners2025`, `dealCount2025`
- meta: `orgCount`(Top 조직 수), `rowCount`(카운터파티 행 수), `offset`, `limit`

### GET `/api/rank/2025/summary-by-size`
- 목적: 규모별 2025/2026 Won 합계(기본 삼성전자 제외)를 빠르게 반환.
- 필터: `exclude_org_name`(기본 "삼성전자"), `years`(콤마 리스트, 기본 2025,2026).
- 집계 규칙: 상태 Won + 계약연도 in years, 조직명이 exclude와 정확히 일치하면 제외, 기업 규모 null/빈값은 `미입력`으로 정규화.
- 캐시: DB mtime + exclude 이름 + years 조합으로 메모리 캐시, 응답에 `snapshot_version=db_mtime:<int>` 포함.
- 응답: `by_size`에 규모별 `sum_2025/sum_2026`, `totals`에 전체 합계, `excluded_org_names`/`years` 메타 포함.

## 엣지/처리 규칙
- 2025 People 랭킹에서 상위 조직과 팀이 모두 없는(`미입력`) 경우는 제외한다(상위 조직만 미입력이고 팀이 있으면 포함).
- 2025 랭킹 응답의 grade/online/offline/2024 합계는 프런트에서 24→25 배수, 2026 목표액(배수 적용), 등급 가이드/배수 모달에 활용한다.
- 조직 목록(`GET /api/orgs`)은 People/Deal 연결이 없는 조직을 제외하고 2025 Won 합계 기준으로 정렬한다(참고: `docs/llm_context/06_API_CONTRACT_CORE.md`).
- 프런트 캐시 무효화 없음: DB 교체 시 브라우저 새로고침 필요.

## Verification
- `/api/rank/2025-deals`가 상태 Won + 계약연도 2025만 포함하고 totalAmount 기준으로 정렬되는지 확인한다.
- `/api/rank/2025-deals-people`가 상위 조직/팀 모두 `미입력`인 행을 제외하고 2025 Won 합계 desc로 정렬되는지 확인한다.
- `/api/rank/mismatched-deals`가 deal.organizationId ≠ people.organizationId 조건을 지키는지 샘플 조회로 확인한다.
- `/api/rank/2025-top100-counterparty-dri`에서 온라인 정의(구독제/선택구매/포팅)와 성사 가능성 필터(확정/높음)가 코드와 일치하는지 확인한다.
- `/api/rank/2025/summary-by-size` 응답에 snapshot_version=db_mtime:<int>가 포함되는지 확인한다.
