---
title: API Behavior Notes (dashboard/server)
last_synced: 2025-12-24
sync_source:
  - dashboard/server/org_tables_api.py
  - dashboard/server/database.py
  - dashboard/server/json_compact.py
  - dashboard/server/statepath_engine.py
  - org_tables_v2.html
---

# API Behavior Notes (dashboard/server)

- 공통
  - 기본 DB 경로: `salesmap_latest.db` (없으면 500).
  - JSON 응답은 FastAPI 라우터(`/dashboard/server/org_tables_api.py`)를 통해 제공된다.

- `/api/orgs/{org_id}/won-groups-json`
  - 조직 메타: `id/name/size/industry`에 더해 `industry_major`(`업종 구분(대)`), `industry_mid`(`업종 구분(중)`)을 포함한다.
  - 웹폼: People 레코드의 `"제출된 웹폼 목록"`을 `{name, date}`로 변환한다. 동일 webFormId의 제출일이 여러 개인 경우 `date`는 리스트가 될 수 있으며, 제출 내역이 없으면 `"날짜 확인 불가"`를 반환한다. webform id는 노출하지 않는다.
  - 메모 정제:
    - 폼 스타일(`키: 값` 줄) + `utm_source` 또는 “고객 마케팅 수신 동의”가 있을 때만 전처리.
    - 드롭 키: 전화/기업 규모/업종/채널/동의/utm 항목과 `ATD's Privacy Notice`, `SkyHive's Privacy Policy`, `개인정보 제3자 제공 동의`.
    - 남은 키가 `고객이름/고객이메일/회사이름/고객담당업무/고객직급/직책`만 있으면 제외.
    - 특수 문구 `(단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청)`이 있으면 해당 메모 제외.

- 기타 주요 엔드포인트
  - `/api/orgs`: People 또는 Deal이 한 건 이상 연결된 조직만 반환, 2025 Won 금액 합계 내림차순(동률 시 이름 순). limit 기본 200.
  - `/api/orgs/{org_id}/won-summary`: 상위 조직별 Won 합계(23/24/25)와 담당자/owner 목록, 2025 Won 딜 데이원 담당자 리스트 `owners2025` 포함.
  - `/api/orgs/{org_id}/people?hasDeal=true|false|null`: 조직의 People 리스트(딜 여부 필터).
  - `/api/people/{person_id}/deals`, `/api/people/{person_id}/memos`, `/api/deals/{deal_id}/memos`: 사람/딜 단위 데이터와 메모.
- 랭킹/이상치: `/api/rank/2025-deals`, `/api/rank/2025-deals-people`, `/api/rank/mismatched-deals`, `/api/rank/won-yearly-totals`, `/api/rank/won-industry-summary`.
- 25/26 규모 합계 요약: `GET /api/rank/2025/summary-by-size`는 상태=Won 딜을 계약연도 기준(기본 2025/2026)으로 규모별 합산. exclude_org_name 기본 “삼성전자”. DB mtime+exclude 조합으로 메모리 캐시(`snapshot_version=db_mtime:<int>`).
- Compact JSON: `/api/orgs/{org_id}/won-groups-json-compact`은 won-groups-json을 축약(schema_version 포함, deal_defaults/summary 추가)한 버전.
- StatePath 단건: `/api/orgs/{org_id}/statepath`는 won-groups-json-compact를 기반으로 2024/2025 State, Path 이벤트, Seed, RevOps 추천을 억 단위 금액으로 반환.
- StatePath 포트폴리오/상세: `/api/statepath/portfolio-2425`, `/api/orgs/{id}/statepath-2425`에서 필터/정렬/버킷/패턴 요약을 제공.
- 카운터파티 상세: `/api/rank/2025-counterparty-dri/detail?orgId=...&upperOrg=...`는 org/upper_org 딜 상세를 반환하며, `deals` 항목에 `people_id/people_name/upper_org`가 포함되어 프런트 팝업의 “상위 조직/교담자” 컬럼을 렌더하는 근거가 된다.

## 딜체크 공통 엔드포인트
- `GET /api/deal-check?team=edu1|edu2` (org_tables_api.py → database.get_deal_check)
  - 대상: `deal."상태"='SQL'`이며 owners 중 team 파라미터에 해당하는 PART_STRUCTURE 구성원이 1명 이상 포함된 딜.
  - 응답 필드: dealId, orgId, orgName, orgWon2025Total, isRetention, createdAt, dealName, courseFormat, owners[], probability, expectedCloseDate, expectedAmount, memoCount, upperOrg, teamSignature, personId, personName.
  - 리텐션 판정: 2025 Won 딜 금액 파싱 성공(>=0)이 있는 orgId. 금액 파싱 실패/NULL 제외, 예상 체결액 미사용.
  - 정렬: orgWon2025Total DESC → createdAt ASC → dealId ASC.
  - memoCount: memo 테이블에서 dealId별 COUNT 후 left join(0이면 프런트에서 비활성 버튼 “메모 없음”).
- 호환 라우트: `/api/deal-check/edu1`, `/api/deal-check/edu2`는 내부적으로 `/api/deal-check?team=...`를 호출.

## Verification
- `/api/deal-check?team=edu1|edu2` 호출 시 personId/personName, memoCount, orgWon2025Total 필드 포함 여부 확인.
- `/api/deal-check` 결과 정렬이 orgWon2025Total DESC → createdAt ASC → dealId ASC인지 샘플 데이터로 검증.
- owners에 해당 팀 멤버가 없는 SQL 딜이 필터링되는지 확인.
- `/api/deals/{deal_id}/memos` 결과 건수와 memoCount가 일치하는지 spot-check.
- `/api/orgs/{org_id}/won-groups-json`에서 industry_major/mid 포함, 웹폼 날짜 변환, 메모 정제 규칙 적용 여부 확인.
- `/api/statepath/portfolio-2425`에서 기본 필터/정렬 응답이 정상인지, cache hit 시에도 동일 응답인지 확인.
- `/api/rank/2025-counterparty-dri/detail` 응답에서 deals[].people_id/people_name/upper_org가 존재하고 프런트 팝업에서 상위 조직/교담자 컬럼으로 노출되는지 확인.
