# 랭킹/집계/이상치 API 계약

## 공통 규칙
- 금액 컬럼은 DB에 TEXT로 저장되며, 백엔드에서 `float`로 변환 후 반환. 프런트는 억 단위(1e8)로 표시.
- 연도 필터는 `계약 체결일`에서 앞 4자리로 판단한다.
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
  - 조건: `상태='Won' AND 계약 체결일 LIKE '2025%'`
  - 온라인: `구독제(온라인)`, `선택구매(온라인)`, `포팅`(완전 일치), 그 외는 비온라인
  - upper_org가 없으면 `미입력`으로 그룹
  - owners2025: deal 담당자 JSON에서 이름/ID 추출 후 유니크 리스트(없으면 `미입력`)
- 정렬: orgWon2025 desc → cpTotal2025 desc (cpTotal은 정렬용, 표시는 하지 않음)
- 반환 필드(행):
  - `orgId/orgName`, `orgTier`(grade), `orgWon2025` (orgOnline/offline는 필요 시만 활용)
  - `upperOrg`, `cpOnline2025`, `cpOffline2025`, `cpTotal2025`, `owners2025`, `dealCount2025`
- meta: `orgCount`(Top 조직 수), `rowCount`(카운터파티 행 수), `offset`, `limit`

## 엣지/처리 규칙
- 2025 People 랭킹에서 상위 조직과 팀이 모두 없는(`미입력`) 경우는 제외한다(상위 조직만 미입력이고 팀이 있으면 포함).
- 2025 랭킹 응답의 grade/online/offline/2024 합계는 프런트에서 24→25 배수, 2026 목표액(배수 적용), 등급 가이드/배수 모달에 활용한다.
- 조직 목록(`GET /api/orgs`)은 People/Deal 연결이 없는 조직을 제외하고 2025 Won 합계 기준으로 정렬한다(참고: `docs/llm_context/06_API_CONTRACT_CORE.md`).
- 프런트 캐시 무효화 없음: DB 교체 시 브라우저 새로고침 필요.
