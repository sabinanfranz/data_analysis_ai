# 메모/웹폼 정제 규칙 (/won-groups-json)

## 1) 웹폼 제출내역 변환
- 입력: People 테이블의 `"제출된 웹폼 목록"`(JSON 배열) + `webform_history`(peopleId/webFormId별 제출 기록).
- 처리:
  - 각 항목을 `{name, date}`로 변환. webForm id는 노출하지 않는다.
  - 같은 `peopleId + webFormId`로 `webform_history`를 조회해 제출일을 모은다.
  - 날짜 규칙: 제출일이 없으면 `"날짜 확인 불가"`, 한 개면 그 날짜(YYYY-MM-DD), 여러 개면 날짜 리스트.
- 출력: People 객체의 `webforms` 배열에 `{name, date}`만 포함.
- 적재 흐름: 스냅샷 후처리에서 Salesmap API 제출 내역을 `webform_history`로 저장한 뒤, `/won-groups-json`에서 이 테이블을 조회해 날짜를 매핑한다(`docs/snapshot_pipeline.md` 참고).

## 2) 메모 정제(폼 스타일 메모만)
- 전처리 대상 조건:
  - 메모 본문이 키:값 형태(라인 단위)이고, `utm_source` 또는 “고객 마케팅 수신 동의” 문자열이 포함될 때만 수행.
  - `(단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청)` 특수 문구가 있으면 전처리 결과를 빈 문자열로 처리(해당 메모 제외).
- 전처리 순서:
  1. 개행 정리: `\n\n` → `\n`, `:)` 제거.
  2. 라인 병합: `:` 없는 줄은 직전 키:값 라인 뒤에 이어 붙인다.
  3. 키 파싱: `:` 앞을 키로 사용하며, 키에서 공백을 제거한 값을 기준으로 필터.
- 제거 대상 키(공백 제거 후 비교):
  - 전화: `고객전화`
  - 기업 규모: `회사기업규모`
  - 업종: `회사업종`
  - 채널: `방문경로`
  - 동의: `개인정보수집동의`, `고객마케팅수신동의`, `ATD'sPrivacyNotice`, `SkyHive'sPrivacyPolicy`, `개인정보제3자제공동의`
  - UTM: `고객utm_source`, `고객utm_medium`, `고객utm_campaign`, `고객utm_content`
- 값이 비어 있거나 `(공백)`/`-`이면 버린다.
- 질문 인식: 키에 `궁금` 또는 `고민`이 있으면 `question` 키로 저장.
- 제외 조건:
  - 전처리 결과가 없으면 `None`(전처리 실패) → 원본 text 유지.
  - 결과 키 집합이 `{고객이름, 고객이메일, 회사이름, 고객담당업무, 고객직급/직책}`만 남으면 빈 문자열로 간주(저장 시 제외).
  - 특수 문구가 있으면 빈 문자열로 간주(저장 시 제외).
- 출력 규칙:
  - 빈 문자열(`""`): 해당 메모를 결과에서 제거.
  - `None`: 전처리 미적용/실패 → 원본 `text` 그대로 둔다.
  - Dict 결과: `text`를 제거하고 `cleanText` 키로 구조화 JSON을 넣는다.

## 3) 적용 위치
- 백엔드: `dashboard/server/database.py`의 `get_won_groups_json`에서 메모/웹폼 변환을 적용해 `groups` 내 People/Deal/Org memos, People webforms에 반영한다. compact 변환에서는 memos/webforms가 제거된다.
- 상세 로직/예제 테스트: `tests/test_won_groups_json.py` 참조.
