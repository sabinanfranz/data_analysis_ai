# 핵심 조회 API 계약 (org_tables_v2.html 사용)

## 공통 규칙
- 기본 DB 경로: 루트 `salesmap_latest.db`. 파일이 없으면 500 오류를 반환한다.
- 금액/날짜 포맷: DB에는 TEXT로 저장, 백엔드에서 그대로 전달(금액은 필요 시 `float` 변환). 프런트는 표시 시 1e8으로 나눠 억 단위 표기, 날짜는 `YYYY-MM-DD`까지만 사용.
- 정렬/필터: 엔드포인트별로 명시(아래 표). 조직 목록은 “People 또는 Deal 연결 있음 + 2025년 Won 합계 내림차순”.
- 캐시: 프런트(JS Map)에만 존재, 무효화 없음. 새 DB로 교체하면 브라우저 새로고침 필요(`docs/org_tables_v2.md` 참고).

## 엔드포인트별 계약
| 메서드/경로 | 목적 | 파라미터 | 정렬/필터 | 응답 스켈레톤 |
| --- | --- | --- | --- | --- |
| GET `/api/sizes` | 조직 규모 목록 조회 | 없음 | DISTINCT, 이름순 | `{ "sizes": ["대기업", ...] }` |
| GET `/api/orgs` | 조직 목록(드롭다운) | `size`(기본 전체), `search`, `limit`(1~500, 기본 200), `offset` | size 필터, People/Deal 1건 이상, 2025 Won 합계 desc, name asc | `{ "items": [ { "id", "name", "size", "team", "owner" } ] }` |
| GET `/api/orgs/{org_id}` | 조직 단건 조회 | path org_id | id 일치 | `{ "item": { "id", "name", "size", "team", "owner" } }` (없으면 404) |
| GET `/api/orgs/{org_id}/memos` | 조직 메모(딜/사람 미연결) | `limit`(1~500, 기본 100) | createdAt desc | `{ "items": [ { "id","text","ownerId","ownerName","createdAt",... } ] }` |
| GET `/api/orgs/{org_id}/people` | 조직 People 리스트 | `hasDeal`(true/false/null) | name asc | `{ "items": [ { "id","organizationId","name","upper_org","team_signature","title_signature","edu_area","email","phone","deal_count" } ] }` |
| GET `/api/people/{person_id}/deals` | 특정 People의 Deal | path person_id | 계약일 desc, NULL 마지막 → 생성일 desc | `{ "items": [ { "id","peopleId","organizationId","name","status","amount","expected_amount","contract_date","owner_json","created_at" } ] }` |
| GET `/api/people/{person_id}/memos` | 특정 People 메모 | `limit`(1~500, 기본 200) | createdAt desc | `{ "items": [ { "id","text","ownerId","ownerName","createdAt",... } ] }` |
| GET `/api/deals/{deal_id}/memos` | 특정 Deal 메모 | `limit`(1~500, 기본 200) | createdAt desc | `{ "items": [ { "id","text","ownerId","ownerName","createdAt",... } ] }` |
| GET `/api/orgs/{org_id}/won-summary` | 상위 조직별 Won 합계(23/24/25) | path org_id | 상위 조직별 그룹, Won 상태 & 계약연도 23/24/25만 합산 | `{ "items": [ { "upper_org","won2023","won2024","won2025","contacts":[...], "owners":[...], "owners2025":[...], "dealCount" } ] }` |
| GET `/api/orgs/{org_id}/won-groups-json` | 상위 조직별 People/Deal JSON | path org_id | 23/24/25 Won 있는 상위 조직만 포함 | `{ "organization": {...}, "groups": [ { "upper_org","team","people":[...], "deals":[...] } ] }` (세부 정제 규칙은 `docs/json_logic.md`) |
| GET `/api/orgs/{org_id}/won-groups-json-compact` | won-groups-json 축약본(LLM용) | path org_id | 원본 그룹 구조를 compact 변환 | `{ "schema_version": "...", "organization": {...,"summary":...}, "groups": [ { "upper_org","team","deal_defaults", "counterparty_summary", "people":[...], "deals":[...] } ] }` |

## 엔드포인트 설명/예시
- `/api/orgs`: People/Deal 연결이 없는 조직은 제외. 2025년 Won 합계 내림차순으로 정렬 후 이름 순으로 보조 정렬.
- `/api/orgs/{id}/won-groups-json`: webform id 미노출, 날짜 매핑(`"날짜 확인 불가"`/단일/리스트), 메모 정제(전화/동의/utm 제거, 특정 문구/정보 부족 시 제외). “고객 마케팅 수신 동의”만 있어도 정제를 시도하며 ATD/SkyHive/제3자 동의 키도 제거한다. 전체 구조/정제 규칙은 `docs/json_logic.md` 참고.
- `/api/orgs/{id}/won-groups-json-compact`: 위 JSON을 LLM 입력용으로 축약(people_id 참조, deal_defaults 추출, summary 블록 추가, 공백/null/빈 배열 제거).
- `/api/orgs/{id}/won-summary`: `상태='Won'`이고 `계약 체결일`이 2023/2024/2025인 금액만 합산. 상위 조직 비어 있으면 `미입력` 그룹에 포함.
- `/api/people/{id}/deals`: 계약일이 NULL인 건은 뒤로 보내고, 그 외 계약일 desc → 생성일 desc.

## 오류/에러 처리
- DB 파일이 없거나 열 수 없으면 500.
- `/api/orgs/{org_id}`는 미존재 시 404, 그 외 대부분 엔드포인트는 조회 실패 시 500.
- 프런트 캐시 무효화 없음: API가 최신 DB를 읽더라도 프런트는 새로고침 전까지 이전 캐시를 사용할 수 있다(`docs/org_tables_v2.md` 참고).
