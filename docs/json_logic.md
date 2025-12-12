# 상위 조직별 JSON 생성 로직 정리

이 문서는 조직/People/Deal 뷰어에서 사용하는 “상위 조직별 JSON”이 어떻게 만들어지는지 설명합니다. 백엔드가 만드는 **전체 JSON**과, 프런트가 상위 조직을 선택했을 때 만드는 **선택 상위 조직 JSON**을 각각 단계별로 풀어 적었습니다. 비개발자도 흐름을 따라 읽을 수 있도록 최대한 서술형으로 정리했습니다.

## 전체 JSON을 만드는 방법 (백엔드)
백엔드 함수: `dashboard/server/database.py`의 `get_won_groups_json(org_id)`.

1. 입력: 조직 ID(`org_id`).
2. 조직 정보 조회:
   - 가져오는 항목: `id`, `name`, `size`(기업 규모), `industry`(업종), `industry_major`(업종 구분 대), `industry_mid`(업종 구분 중).
   - 조직 메모(organizationId만 연결된 memo)도 함께 가져온다. 폼 스타일 메모는 사전에 정제된다(불필요 키 제거, 특정 문구 제외 등).
3. People 조회:
   - 항목: `id`, `name`, `upper_org`(소속 상위 조직), `team_signature`(팀), `title_signature`(직급), `edu_area`(담당 교육 영역), `제출된 웹폼 목록`.
   - 웹폼 목록 파싱: 각 항목에서 `id`와 `name`만 남긴다. id는 표시하지 않는다.
4. 웹폼 제출 기록 매핑:
   - 테이블 `webform_history`에서 People id + webform id가 같은 행을 찾아 제출일을 모은다.
   - 날짜가 없으면 `"날짜 확인 불가"`, 한 개면 그 날짜(YYYY-MM-DD), 여러 개면 날짜 리스트로 넣는다.
5. 딜 조회:
   - 이 조직의 모든 딜(상태 무관)을 가져온다. 항목: id, 이름, 상태, 금액/예상 금액, 계약/생성일, 과정포맷 등 + 딜에 연결된 People 정보.
   - 딜 메모도 로드하고, 폼 스타일이면 정제하여 `cleanText`로 교체한다. 정제가 불가능하면 원문 text를 둔다.
6. 대상 상위 조직 결정:
   - 2023/2024/2025년 Won 딜이 존재하는 상위 조직만 그룹 대상에 포함한다.
7. 그룹 구성:
   - 기준: `upper_org` + `team`.
   - 각 그룹에 People 배열, Deal 배열을 채운다.
   - People에는 webforms(날짜 매핑된 형태)와 person memo가 포함된다.
   - Deal에는 deal memo와 함께 People 기본 정보가 중첩된다.
8. 정렬:
   - 그룹 리스트는 `upper_org`, `team` 순으로 정렬한다.
9. 최종 반환 구조:
   ```json
   {
     "organization": {
       "id": "...",
       "name": "...",
       "size": "...",
       "industry": "...",
       "industry_major": "...",
       "industry_mid": "...",
       "memos": [ ... ]
     },
     "groups": [
       {
         "upper_org": "...",
         "team": "...",
         "people": [ ... ],
         "deals": [ ... ]
       },
       ...
     ]
   }
   ```

## 선택 상위 조직 JSON을 만드는 방법 (프런트엔드)
프런트 파일: `org_tables_v2.html`.

1. 전체 JSON 가져오기:
   - 회사 선택 시 `/api/orgs/{orgId}/won-groups-json`을 한 번 호출하고 캐시에 저장한다.
2. 상위 조직 선택:
   - 화면의 상단 표(상위 조직 Won 합계)에서 상위 조직을 클릭하면 선택 값이 설정된다.
3. 필터링:
   - 함수 `filterWonGroupByUpper(전체JSON, 선택된 상위 조직)`에서 `groups` 배열을 `upper_org`가 같은 것만 남긴다.
   - 선택이 없으면 필터 결과는 빈 상태이며 JSON 버튼이 비활성화된다.
4. 버튼/모달 동작:
   - “JSON 확인/복사(전체)” → 전체 JSON 그대로 사용.
   - “JSON 확인/복사(선택 상위 조직)” → 필터링된 JSON을 사용.
   - 선택이 없으면 버튼 비활성 + 안내 문구 “아래 표에서 소속 상위 조직을 선택해주세요”.
5. 결과 형태:
   - 구조는 전체 JSON과 동일하며, `groups`에 선택한 상위 조직만 남는다. `organization` 블록은 그대로 유지된다.

## 메모/웹폼 정제 간단 메모
- 폼 메모 정제:
  - `utm_source`가 있어야 정제 진행.
  - 전화/기업 규모/업종/채널/동의/utm 항목은 제거.
  - 남는 키가 `고객이름/고객이메일/회사이름/고객담당업무/고객직급/직책`만이면 제외.
  - 특수 문구 `(단, 1차 유선 통화시 미팅이 필요하다고 판단되면 바로 미팅 요청)`이 있으면 제외.
  - 그 외에는 `cleanText`로 구조화하고, 정제 실패 시 원문 text 유지.
- 웹폼 날짜:
  - 제출 기록이 없으면 `"날짜 확인 불가"`.
  - 한 건이면 날짜 문자열, 여러 건이면 날짜 리스트.
  - id는 노출하지 않고 `{name, date}`만 사용.

## 확인/테스트 방법
- 백엔드 단독 확인:
  - 파이썬에서 직접 호출:  
    ```bash
    python3 - <<'PY'
    from dashboard.server import database as db
    org_id = "샘플_ORG_ID"
    data = db.get_won_groups_json(org_id)
    print(data.keys())
    print("groups:", len(data.get("groups", [])))
    PY
    ```
- 프런트 확인:
  1) `org_tables_v2.html`을 열고 회사를 선택한다.
  2) 상위 조직 표에서 한 행을 클릭해 선택한다.
  3) “JSON 확인/복사” 버튼으로 전체/선택 JSON을 열어 구조가 의도대로 필터링되었는지 확인한다.
