# API Behavior Notes (dashboard/server)

- 공통
  - 기본 DB 경로: `salesmap_latest.db` (없으면 500).
  - JSON 응답은 FastAPI 라우터(`/dashboard/server/org_tables_api.py`)를 통해 제공된다.

- `/api/orgs/{org_id}/won-groups-json`
  - 조직 메타: `id/name/size/industry`에 더해 `industry_major`(`업종 구분(대)`), `industry_mid`(`업종 구분(중)`)을 포함한다.
  - 웹폼: People 레코드의 `"제출된 웹폼 목록"`을 `{name, date}`로 변환한다. 동일 webFormId의 제출일이 여러 개인 경우 `date`는 리스트가 될 수 있으며, 제출 내역이 없으면 `"날짜 확인 불가"`를 반환한다. webform id는 노출하지 않는다.
  - 메모 정제:
    - 폼 스타일(`키: 값` 줄) + `utm_source`가 있을 때만 전처리.
    - 드롭 키: 전화/기업 규모/업종/채널/동의/utm 항목은 제거한다.
    - 남은 키가 `고객이름/고객이메일/회사이름/고객담당업무/고객직급/직책`만 있으면 메모를 결과에서 제외한다.
    - 의미 있는 정제 결과가 있으면 `text`를 구조화된 JSON 문자열로 대체한다. 전처리 대상이 아니거나 실패하면 원본 `text`를 그대로 둔다.
    - 특수 문구 `(단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청)`이 있으면 해당 메모를 결과에서 제외한다.

- 기타 주요 엔드포인트
  - `/api/orgs`: People 또는 Deal이 한 건 이상 연결된 조직만 반환하며, 2025년 Won 금액 합계 내림차순으로 정렬(동률 시 이름 순). limit 기본 200.
  - `/api/orgs/{org_id}/won-summary`: 상위 조직별 Won 합계(23/24/25)와 담당자/owner 목록을 반환하며, 2025 Won 딜의 데이원 담당자 리스트 `owners2025`를 추가로 포함한다.
  - `/api/orgs/{org_id}/people?hasDeal=true|false|null`: 조직의 People 리스트(딜 여부 필터).
  - `/api/people/{person_id}/deals`, `/api/people/{person_id}/memos`, `/api/deals/{deal_id}/memos`: 사람/딜 단위 데이터와 메모.
  - 랭킹/이상치: `/api/rank/2025-deals`(grade/grade2024 + online/offline/2024 합계 포함), `/api/rank/2025-deals-people`, `/api/rank/mismatched-deals`, `/api/rank/won-yearly-totals`, `/api/rank/won-industry-summary`.
  - Compact JSON: `/api/orgs/{org_id}/won-groups-json-compact`은 won-groups-json을 LLM용으로 축약(schema_version 포함, deal_defaults/summary 추가)한 버전을 반환한다.
  - StatePath 단건: `/api/orgs/{org_id}/statepath`는 won-groups-json-compact를 내부 생성해 2024/2025 State, Path 이벤트, Seed, RevOps 추천(타겟 셀/카운터파티/액션)을 억 단위 금액과 함께 반환한다.
  - StatePath 포트폴리오/상세:
    - `GET /api/statepath/portfolio-2425`: 규모/검색/정렬/패턴 필터(segment, search, sort, limit, offset, riskOnly, hasOpen, hasScaleUp, companyDir, seed, rail, railDir, companyFrom/To, cell, cellEvent) 기준으로 24/25 회사 총액(억)·버킷과 4셀/online·offline 버킷, 셀 금액, seed, 이벤트 카운트 등을 내려준다. `summary`에는 회사 버킷 전이 매트릭스, 4셀 이벤트 매트릭스, rail 변화 요약, top patterns, (전체 탭 기본 필터일 때) 세그먼트 비교가 포함된다.
    - `GET /api/orgs/{id}/statepath-2425`: 단일 조직의 24/25 State + Path + QA, sizeGroup을 DB 집계 기반으로 반환한다(포트폴리오와 일관).

## 메모 정제 트리거/드롭 키 보강
- 트리거: `utm_source`가 있거나 “고객 마케팅 수신 동의” 문구가 있을 때 폼 스타일 메모를 정제한다.
- 드롭 키 추가: `ATD's Privacy Notice`, `SkyHive's Privacy Policy`, `개인정보 제3자 제공 동의`도 제거 대상이다.
