# won-groups-json AttributeError 조사 보고서 (sqlite3.Row.get)

## Step0 재현 로그 (500 확인)
- 서버 실행: `DEBUG_WON_JSON=1 uvicorn dashboard.server.main:app --port 8000 --log-level debug`
- 재현 요청 1: `GET /api/orgs/64d3287c1750f5b1d531c5bf/won-groups-json` → HTTP 500
- 재현 요청 2: `GET /api/orgs/64d3287c1750f5b1d531c5bf/won-groups-json-compact` → HTTP 500
- Stacktrace (요청1, 마지막 30여 줄):
```
  File ".../dashboard/server/org_tables_api.py", line 615, in get_won_groups_json
    return db.get_won_groups_json(org_id=org_id)
  File ".../dashboard/server/database.py", line 3113, in get_won_groups_json
    "created_at_ts": memo.get("createdAt"),
                     ^^^^^^^^
AttributeError: 'sqlite3.Row' object has no attribute 'get'
WARNING:root:[won-json-debug] memo_type=<class 'sqlite3.Row'> has_keys=True keys=['id', 'dealId', 'peopleId', 'organizationId', 'text', 'createdAt', 'htmlBody'] createdAt=2023-08-24T06:28:28.660Z
```
- Stacktrace (요청2, compact, 동일 위치):
```
  File ".../dashboard/server/org_tables_api.py", line 623, in get_won_groups_json_compact
    raw = db.get_won_groups_json(org_id=org_id)
  File ".../dashboard/server/database.py", line 3113, in get_won_groups_json
    "created_at_ts": memo.get("createdAt"),
                     ^^^^^^^^
AttributeError: 'sqlite3.Row' object has no attribute 'get'
WARNING:root:[won-json-debug] memo_type=<class 'sqlite3.Row'> has_keys=True keys=['id', 'dealId', 'peopleId', 'organizationId', 'text', 'createdAt', 'htmlBody'] createdAt=2023-08-24T06:28:28.660Z
```

## Step1 런타임 모듈 경로/mtime (DEBUG_WON_JSON=1)
- `GET /api/_debug/won-json-runtime` 결과:
```
{
  "db_file": "/mnt/c/Users/admin/Desktop/B2B/data_analysis_ai/dashboard/server/database.py",
  "db_mtime": 1770174727.5522656,
  "has_memo_get_createdAt": true,
  "created_at_ts_occurrences": [3113, 3121]
}
```
- 실제 실행 파일이 repo의 `dashboard/server/database.py`이며 mtime=1770174727.5522656(현 체크아웃 기준) 확인.

## Step2 검색 결과 (코드 전수)
- `memo.get("createdAt")` 일치:
  - dashboard/server/database.py:3113: `"created_at_ts": memo.get("createdAt"),`
  - dashboard/server/database.py:3121: `"created_at_ts": memo.get("createdAt"),`
  - dashboard/server/org_tables_api.py: debug endpoint 검사 문자열
- `.get("createdAt")` 전체(py):
  - dashboard/server/database.py:3113, 3121 (위와 동일)
  - dashboard/server/database.py:3375: `x.get("createdAt") or ""` (owner JSON 파싱 dict 대상)
  - dashboard/server/org_tables_api.py: debug 문자열
- `get_won_groups_json` 함수 내 `.get(` 전수(라인 기준):
  - 2957: `wf_id = entry.get("id") or entry.get("webFormId") or entry.get("webformId")`
  - 2958: `name = entry.get("name") or entry.get("title")`
  - 3033: `wf_id = entry.get("id")`
  - 3034: `dates = webform_history_index.get((pid, wf_id)) if wf_id else None`
  - 3043: `cleaned = {"name": entry.get("name", "")}`
  - 3113: `"created_at_ts": memo.get("createdAt"),`
  - 3121: `"created_at_ts": memo.get("createdAt"),`
  - 3143: `person = people_map.get(pid)`
  - 3177: `"memos": person_memos.get(person["id"], []),`
  - 3184: `person = people_map.get(pid)`
  - 3190: `owner_name = owner.get("name") or owner.get("id")`
  - 3221: `"memos": deal_memos.get(row["id"], []),`

## Step3 문제 라인 스니펫 (database.py 3070–3132)
```
3108        if cleaned is None:
3109            entry = {
3110                "date": date_only,
3111                "text": memo["text"],
3112                "htmlBody": html_body,
3113                "created_at_ts": memo.get("createdAt"),
3114            }
3115        else:
3116            entry = {
3117                "date": date_only,
3118                "cleanText": cleaned,
3119                "htmlBody": html_body,
3120                "created_at_ts": memo.get("createdAt"),
3121            }
3122        deal_id = memo["dealId"]
3123        person_id = memo["peopleId"]
3124        org_only = memo["organizationId"]
```

## Step4 런타임 memo 타입 증거
- DEBUG 로그(1회 샘플):
  - `[won-json-debug] memo_type=<class 'sqlite3.Row'> has_keys=True keys=['id', 'dealId', 'peopleId', 'organizationId', 'text', 'createdAt', 'htmlBody'] createdAt=2023-08-24T06:28:28.660Z`
- 타입이 `sqlite3.Row`이며 `.get` 메서드가 없어 예외가 발생함을 직접 확인.

## Step5 비슷한 오류 가능성이 있는 `.get` 호출 후보
- get_won_groups_json 내부에서 Row 대상으로 쓰일 수 있는 `.get`은 위 3113/3121 두 군데뿐.
- 나머지 `.get` 호출들은 dict 대상(owner, people_map entry, webform entry)로 Row 타입 아님 → 동일 에러 가능성 낮음.

## Step6 가설 검증 표
| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| H1: 실행 중인 database.py가 다른 위치다 | Debug endpoint db_file=/mnt/c/.../dashboard/server/database.py, mtime 매치 | 기각 |
| H2: memo.get("createdAt") 호출이 여전히 존재한다 | 코드 라인 3113/3121, debug endpoint has_memo_get_createdAt=true | 확정 |
| H3: memo가 dict가 아니라 sqlite3.Row라서 .get이 없다 | DEBUG 로그 memo_type=sqlite3.Row, keys 출력, stacktrace AttributeError | 확정 |
| H4: 서버 reload 미반영 | uvicorn fresh run + mtime 확인, 여전히 same code → reload 문제 아님 | 기각 |

## 최종 결론
- 원인: `get_won_groups_json`에서 memo를 `sqlite3.Row` 그대로 사용하면서 `.get("createdAt")` 호출(3113, 3121)을 수행해 AttributeError가 발생. memo는 dict로 변환되지 않았고 Row에는 `.get` 메서드가 없음.

## 다음 조치(패치 방향 제안)
1) memo 접근을 dict 스타일로 교체: `memo.get("createdAt")` → `memo["createdAt"]` (또는 `memo.get` 대신 `memo["createdAt"] if "createdAt" in memo.keys() else None`).
2) 대안으로 루프 초기에 `memo = dict(memo)` 변환해 Row를 dict로 표준화한 뒤 `.get` 사용.
3) 회귀 방지: pytest 추가 (Row → .get AttributeError 방지 케이스) 및 DEBUG_WON_JSON 가드된 로깅/엔드포인트 제거.
