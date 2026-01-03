---
title: SQLite 데이터 모델 요약 (deal/people/organization/memo)
last_synced: 2025-12-26
sync_source:
  - salesmap_first_page_snapshot.py
  - dashboard/server/database.py
  - dashboard/server/org_tables_api.py
  - org_tables_v2.html
  - salesmap_latest.db (PRAGMA table_info)
---

# SQLite 데이터 모델 요약 (deal/people/organization/memo)

## Purpose
- 스냅샷 DB(`salesmap_latest.db`)의 핵심 테이블 deal/people/organization/memo 컬럼 정의와 관계를 코드·실제 스키마 기준으로 정확히 기록한다.
- 리팩토링 시 스키마 계약, 파싱 규칙(TEXT→숫자/날짜), 관계 키를 보호하기 위한 근거 자료를 제공한다.

## Behavioral Contract
- 생성/교체: `salesmap_first_page_snapshot.py`가 Salesmap API를 적재해 `salesmap_latest.db`를 생성/교체한다. FastAPI는 캐시 없이 이 DB를 직접 읽으며, 교체 후 프런트 새로고침이 필요하다.
- 관계:
  - `organization.id` = `people.organizationId`
  - `people.id` = `deal.peopleId`
  - `organization.id` = `deal.organizationId`
  - `memo`는 `dealId` 또는 `peopleId` 또는 `organizationId`로 다대1 연결(없을 수 있음).
- 타입: 핵심 테이블 모든 컬럼은 TEXT로 저장된다(숫자/날짜는 런타임 파싱). 금액/날짜 표기는 화면별 포맷 규칙을 따른다.

## Invariants (Must Not Break)
- 테이블 존재: `deal`, `people`, `organization`, `memo`가 존재해야 한다(`PRAGMA table_info` 기준).
- ID/링크: 각 테이블 `id (TEXT)` 필수, 관계 키(`organizationId/peopleId/dealId`)는 TEXT 그대로 유지.
- 컬럼 불변: 아래 나열된 컬럼 이름/타입(TEXT)을 제거·타입 변경하지 않는다(추가만 허용). 파서·UI는 이 이름에 의존한다.
- 파싱/포맷: 금액/날짜 TEXT는 백엔드 `_to_number`/슬라이싱 후 API로 전달, 프런트는 억 단위 소수 1~2자리와 YYYY-MM-DD/YYMMDD 포맷을 적용한다.

## Coupling Map
- 파이프라인: `salesmap_first_page_snapshot.py` → `salesmap_latest.db` → CI(`.github/workflows/salesmap_db_daily.yml` Release) → 런타임 `start.sh` 다운로드/`DB_PATH` 설정.
- 백엔드: `dashboard/server/database.py`가 deal/people/organization/memo를 읽어 파싱/집계, `org_tables_api.py`에서 API로 노출.
- 프런트: `org_tables_v2.html`이 API 응답을 사용해 금액/날짜 포맷을 적용.

## Edge Cases & Failure Modes
- TEXT 파싱 실패: 숫자/날짜가 비정상·빈값이면 백엔드 파서에서 null 처리 → 합산 시 0 또는 "-"로 표시.
- 링크 누락: deal.peopleId/organizationId가 비어 있으면 조인 결과가 누락될 수 있음. memo도 링크 없으면 고아 메모.
- DB 교체 후 캐시 없음: 새 스냅샷 배포 후 프런트 새로고침 필요.

## 테이블별 컬럼 정의 (PRAGMA table_info 기반, 모두 TEXT)
### deal
- id, peopleId, organizationId, (온라인)입과 주기, (온라인)최초 입과 여부, LOST 확정일, Net(%), RecordId, SDR (AE 배정 후), SQL 전환일, utm_campaign, utm_content, utm_medium, utm_source, 강사 이름1~5, 강사료1~5, 계약 체결일, 과정포맷, 교육 시작월(예상), 교육 주제, 구독 시작 유형/시작일/종료 유형/종료일, 금액, 기업 니즈, 누적 시퀀스 등록수, 다음 TODO 날짜/연락일, 담당 파트/담당자, 등록된 시퀀스 목록, 딜 전환 유형, 리드 목록, 마감일, 메인 견적 상품 리스트, 문의 주제(최초/후속), 미완료 TODO, 방문 경로, 상담 문의 내용, 상태, 생성 날짜, 서비스 유형(최초/후속), 성사 가능성, 소스, 수강시작일, 수강종료일, 수료 조건(온라인), 수정 날짜, 수주 예정일/(지연), 실제 수주액, 실패 사유/상세, 업로드 제안서명, 예상 교육 인원/일정/입금일자/체결액, 완료 TODO, 운영 담당자/(사용X), 월 구독 금액, 이름, 이탈 사유, 입과자(온라인), 입찰/PT 여부, 전체 TODO, 제안서 발송일/작성 여부, 참여자, 최근 노트 작성일/작성자, 최근 등록한 시퀀스, 최근 시퀀스 등록일, 최근 연락일, 최근 웹폼 제출 날짜, 최근 작성된 노트, 최근 제출된 웹폼, 최근 파이프라인 단계/수정 날짜, 카테고리, 코스 ID, 팀, 파이프라인, 파이프라인 단계, 팔로워, 현재 진행중인 시퀀스 여부.

### people
- id, organizationId, AI 교육 니즈, Label, RecordId, utm_campaign/content/medium/source, 고객 그룹/상태/여정 단계, 공개형 교육, 관리 여부, 관심사, 누적 시퀀스 등록수, 뉴스레터, 다음 TODO 날짜, 담당 교육 영역/업무/담당자, 등록된 시퀀스 목록, 딜 개수, 리드 개수, 리텐션 관리 여부, 링크드인, 마케팅 수신 동의, 미완료 TODO, 비즈레터 구독(사용X), 생성 날짜, 성사된 딜 개수, 세미나참석, 세일즈 유관 고객 관리, 소속 상위 조직, 소스, 수신 거부 사유/여부, 수정 날짜, 숨참, 신규 MQL, 실패된 딜 개수, 연락처 이슈, 온라인TF 관리 중, 완료 TODO, 웨비나, 이름, 이메일, 전체 TODO, 전화, 제출된 웹폼 목록, 직급(명함/메일서명), 직급/직책, 진행중 딜 개수, 참여자(딜/리드), 총 매출, 최근 고객 활동일, 최근 노트 작성일/작성자, 최근 등록한 시퀀스, 최근 시퀀스 등록일, 최근 연락일, 최근 웹폼 제출 날짜, 최근 유선 연락일, 최근 이메일 받은/보낸/연락/오픈일, 최근 작성된 노트, 최근 제출된 웹폼, 콘텐츠/행사 신청 배경, 팀, 팀(명함/메일서명), 포지션, 프로필 사진, 현재 진행중인 시퀀스 여부.

### organization
- id, LMS 교체일, Label, RecordId, 공개교육 수강, 관리 상태, 기업 규모, 기업 순위, 기업집단명, 다음 TODO 날짜, 담당자, 딜 개수, 리드 개수, 링크드인, 미완료 TODO, 사업자등록번호, 생성 날짜, 성사된 딜 개수, 소스, 수정 날짜, 실패된 딜 개수, 업종, 업종 구분(대)/(중), 업종 세부, 완료 TODO, 웹 주소, 이름, 이메일, 전체 TODO, 전화, 제출된 웹폼 목록, 주소, 직원수, 진행중 딜 개수, 총 매출, 최근 노트 작성일/작성자, 최근 웹폼 제출 날짜, 최근 작성된 노트, 최근 제출된 웹폼, 팀, 프로필 사진.

### memo
- id, cursorId, text, dealId, leadId, peopleId, organizationId, productId, quoteId, todoId, parentId, ownerId, updatedAt, createdAt.

## Verification
- `PRAGMA table_info('deal'|'people'|'organization'|'memo')` 결과가 위 컬럼 목록과 일치하는지 확인한다.
- 금액/날짜 TEXT 파싱이 백엔드 `_to_number`/슬라이싱과 프런트 포맷 규칙(`formatAmount*`, `formatDate*`)과 일치하는지 샘플 API 조회로 확인한다.
- 관계 키(people.organizationId, deal.peopleId/deal.organizationId, memo.*Id)가 null/빈값일 때 조인/집계가 적절히 처리되는지 API 응답을 통해 검증한다.
- 스냅샷 교체 후 프런트 새로고침 시 최신 DB가 반영되는지(캐시 없음) 확인한다.

## Refactor-Planning Notes (Facts Only)
- 모든 핵심 테이블 컬럼이 TEXT로 고정되어 있어 숫자/날짜 파싱이 전적으로 애플리케이션 로직에 의존한다(타입 변경 시 파서/포맷 전면 수정 필요).
- 인덱스가 선언돼 있지 않아 FK 조인 성능이 대규모 데이터에서 취약할 수 있음(people/organization/deal/memo FK 컬럼 인덱스 고려 대상).
- 스냅샷→Release→start.sh 다운로드 체인에 DB 교체가 의존하며, 캐시가 없어 교체 후 클라이언트 새로고침이 필수이다.
