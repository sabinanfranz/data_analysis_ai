# 용어집 (Glossary)

프로젝트 전반에서 반복적으로 등장하는 핵심 용어를 정규화된 표기/정의와 함께 정리한다. 필드명·테이블명은 실제 SQLite 스냅샷 스키마(dashboard/server/database.py 참조)를 기준으로 기재한다.

## Organization / Org / 회사
- 정의: 고객사(organization) 단위 레코드. 규모/팀/담당자 정보를 담는다.
- 원천(Source of truth): SQLite `organization` 테이블 (`id`, `"이름"`, `"기업 규모"`, `"팀"` JSON, `"담당자"` JSON), API `/api/orgs/{id}/*`, 프런트 org_tables_v2 메뉴 전반.
- 비고/주의: `"이름"`이 비어 있으면 `id`로 대체. 규모 필터는 `"기업 규모"`를 사용하며 `infer_size_group`(database.py)로 표준화한다.
- 예시: `"기업 규모"="대기업"`, `"팀"=[{"name":"교육팀"}]`.

## People / 인물
- 정의: 조직에 소속된 개인. 상위 조직/팀/직급/교육영역 메타가 포함된다.
- 원천: SQLite `people` 테이블 (`id`, `"이름"`, `"소속 상위 조직"`, `"팀(명함/메일서명)"`, `"직급(명함/메일서명)"`, `"담당 교육 영역"`), API `/api/orgs/{id}/people`.
- 비고/주의: 상위 조직/팀은 공백이면 `"미입력"`으로 정규화. org_tables_v2에서 카운터파티(upper_org) 분류와 DRI 판정에 사용.
- 예시: `"소속 상위 조직"="HRD본부"`, `"팀(명함/메일서명)"="HR"` .

## Deal / 딜
- 정의: 영업 기회·계약 단위 레코드. 금액/상태/일자/과정포맷/담당자 등을 가진다.
- 원천: SQLite `deal` 테이블 (`id`, `"이름"`, `"상태"`, `"금액"`, `"예상 체결액"`, `"계약 체결일"`, `"생성 날짜"`, `"과정포맷"`, `"담당자"` JSON, `organizationId`, `peopleId`), API `/api/orgs/{id}/won-summary`, `/api/orgs/{id}/won-groups-json`, 랭킹/StatePath 엔드포인트.
- 비고/주의: 금액은 `금액>0` 없으면 `예상 체결액>0`을 사용. 연도 판단은 `"계약 체결일"` 우선, 없으면 `"생성 날짜"`. 상태 `"Won"`만 집계에 포함하는 경우가 많음.
- 예시: `"상태"="Won"`, `"과정포맷"="구독제(온라인)"`, `"계약 체결일"="2025-03-01"`.

## Memo / 메모
- 정의: Org/People/Deal에 연결된 자유서식 메모.
- 원천: SQLite `memo` 테이블 (`organizationId`, `peopleId`, `dealId`, `ownerId`, `text`), API `/api/orgs/{id}/memos`, `/api/people/{id}/memos`, `/api/deals/{id}/memos`.
- 비고/주의: `_clean_form_memo`(database.py)로 마케팅 폼 관련 항목만 추려 LLM 컨텍스트에 사용. `ownerId`는 `_get_owner_lookup`으로 이름 매핑.
- 예시: `ownerName="홍길동"`, `text="고객 문의: ..."`.

## Won / Won 상태
- 정의: `"상태"='Won'`인 딜. 집계·랭킹·StatePath 모두 Won만 포함.
- 원천: `deal."상태"` 필드, 다수 API에서 필터로 사용.
- 비고/주의: 연도 필터는 `"계약 체결일" LIKE 'YYYY%'` 규칙을 고정적으로 사용(2023/2024/2025 등).
- 예시: `status='Won'`, `contract_date='2025-02-01'`.

## 계약 체결일 / Contract Date
- 정의: 딜 체결일 문자열(YYYY-MM-DD). 연도 판단의 1순위.
- 원천: `deal."계약 체결일"`.
- 비고/주의: 비어 있으면 `"생성 날짜"`로 연도 대체. 파싱 실패 시 제외. 앞 4자리를 연도로 사용.
- 예시: `"계약 체결일"="2025-07-16"`.

## 기업 규모 / Size / Size Group
- 정의: 조직의 규모 구분. 원본 텍스트와 표준화 그룹이 존재.
- 원천: `organization."기업 규모"`, API `list_sizes`, `infer_size_group`(database.py)로 `대기업/중견기업/중소기업/공공기관/대학교/기타/미입력` 그룹 생성. 프런트 StatePath/랭킹의 규모 선택에 사용.
- 비고/주의: 이름 키워드로 공공/대학교 판별, 공백은 `"기타/미입력"`.
- 예시: `"기업 규모"="대기업"`, `sizeGroup="공공기관"`.

## 상위 조직 / Upper Org / 소속 상위 조직
- 정의: People(또는 Deal 연결 인물)의 상위 조직(부서/본부)명. 카운터파티 단위 집계에 사용.
- 원천: `people."소속 상위 조직"`, deal 조인 시 `p."소속 상위 조직"`, 프런트에서는 `normalizeUpperOrg`로 공백을 `"미입력"` 처리.
- 비고/주의: org_tables_v2의 카운터파티 DRI 메뉴에서 upper_org=카운터파티. 정규화 표기: `Upper Org` 또는 `소속 상위 조직`.
- 예시: `"소속 상위 조직"="경영기획본부"`, 없으면 `"미입력"`.

## 팀 / Team
- 정의: People의 팀(명함/메일서명) 문자열. 카운터파티 상세 팀별 딜 집계에 사용.
- 원천: `people."팀(명함/메일서명)"`, won-groups-json `group.team`.
- 비고/주의: 공백은 `"미입력"`으로 정규화. DRI 판정에서는 PART_STRUCTURE 매핑 결과의 팀/파트를 사용(프런트 상수).
- 예시: `"팀(명함/메일서명)"="HR"`.

## 과정포맷 / Course Format
- 정의: 딜 진행 방식. 온라인/비온라인 분류에 사용.
- 원천: `deal."과정포맷"`.
- 비고/주의: 온라인 판정 고정 리스트 = `구독제(온라인)`, `선택구매(온라인)`, `포팅` (정확히 일치). 그 외는 비온라인. 랭킹·StatePath·카운터파티 DRI 집계에서 동일 규칙 사용.
- 예시: `"과정포맷"="포팅" → ONLINE`, `"과정포맷"="포팅/SCORM" → OFFLINE`.

## 담당자(JSON) / Owner
- 정의: 딜/조직/People 레코드에 포함된 담당자 JSON(이름/ID).
- 원천: `deal."담당자"`, `organization."담당자"`, `people."담당자"`.
- 비고/주의: `_safe_json_load`로 파싱 후 name/id 추출. 공백은 `"미입력"`. 카운터파티 DRI, won-summary에서 중복 제거 후 리스트로 노출.
- 예시: `{"id":"u-1","name":"홍길동"}` → `owners2025=["홍길동"]`.

## 팀&파트 / PART_STRUCTURE 매핑
- 정의: 프런트 상수 `PART_STRUCTURE`(org_tables_v2.html)로 담당자 이름을 팀/파트(또는 셀)에 매핑한 결과.
- 원천: 프런트 JS 상수 및 `computeTeamPartSummary` 함수.
- 비고/주의: 이름 정규화(trim, 영문 1글자 suffix 제거) 후 단일 팀·파트(셀 제외)일 때만 DRI=O. 복수/미매핑/셀 포함이면 DRI=X.
- 예시: `"김솔이" → 기업교육 1팀 1파트`, DRI=O.

## Webform
- 정의: 제출된 웹폼 기록(날짜/제목 리스트).
- 원천: `won-groups-json` 응답의 `webforms` 배열, 프런트 `getWebformsForPerson`/`openWebformModal`.
- 비고/주의: People 상세/카운터파티 상세에서 버튼으로 노출. 없으면 비활성화.
- 예시: `{"name":"2024-10-01 컨택","date":"2024-10-01"}`.
