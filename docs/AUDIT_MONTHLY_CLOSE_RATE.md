# 2026 체결률 현황 계약 감사 보고서

- 생성시각: 2026-02-03T01:10:11.714386Z

## Executive Summary

- FAIL: 4 / 11 항목

  - ❌ FE_UNDEFINED_INQUIRY_SIZE_GROUPS: ['org_tables_v2.html uses INQUIRY_SIZE_GROUPS 1 times but no const definition found']

  - ❌ SUMMARY_PARAMS_FE_BE_MATCH: ["FE params: ['from', 'to', 'cust', 'scope']", "BE params: ['from_month: str', 'alias', 'description']"]

  - ❌ DEALS_PARAMS_FE_BE_MATCH: ["FE params: ['segment', 'row']", "BE params: ['segment: str', 'description']"]

  - ❌ SIZE_GROUPS_MATCH: ['FE size groups: []', "BE size groups: ['대기업', '중견기업', '중소기업', '공공기관', '대학교', '기타', '미기재']"]


## SSOT Tables

- FE CLOSE_RATE_COURSE_GROUPS: ['구독제(온라인)', '선택구매(온라인)', '포팅', '오프라인'] (line 2313)

- BE CLOSE_RATE_COURSE_GROUPS: ['구독제(온라인)', '선택구매(온라인)', '포팅', '오프라인'] (line 167)

- FE CLOSE_RATE_METRICS: ['total', 'confirmed', 'high', 'low', 'lost', 'close_rate'] (line 2314)

- BE CLOSE_RATE_METRICS: ['total', 'confirmed', 'high', 'low', 'lost', 'close_rate'] (line 168)

- FE scope keys: ['all', 'corp_group', 'edu1', 'edu2', 'edu1_p1', 'edu1_p2', 'edu2_p1', 'edu2_p2', 'edu2_online'] (line 2323)

- BE scope keys: ['all', 'corp_group', 'edu1', 'edu2', 'edu1_p1', 'edu1_p2', 'edu2_p1', 'edu2_p2', 'edu2_online'] (line None)

- FE size groups (defined?): [] (uses: 1)

- BE size groups: ['대기업', '중견기업', '중소기업', '공공기관', '대학교', '기타', '미기재']


## Contract Diff

- FE_UNDEFINED_INQUIRY_SIZE_GROUPS: FAIL | Evidence: ['org_tables_v2.html uses INQUIRY_SIZE_GROUPS 1 times but no const definition found']

- SUMMARY_PARAMS_FE_BE_MATCH: FAIL | Evidence: ["FE params: ['from', 'to', 'cust', 'scope']", "BE params: ['from_month: str', 'alias', 'description']"]

- DEALS_PARAMS_FE_BE_MATCH: FAIL | Evidence: ["FE params: ['segment', 'row']", "BE params: ['segment: str', 'description']"]

- SIZE_GROUPS_MATCH: FAIL | Evidence: ['FE size groups: []', "BE size groups: ['대기업', '중견기업', '중소기업', '공공기관', '대학교', '기타', '미기재']"]


## API Contract Check

- FE summary params: ['from', 'to', 'cust', 'scope']
- BE summary params: ['from_month: str', 'alias', 'description']

- FE deals params: ['segment', 'row']
- BE deals params: ['segment: str', 'description']


## Risk Hotspots

- FE ReferenceError: INQUIRY_SIZE_GROUPS is used but not defined.


## Next Fix Order

1) Define or remove INQUIRY_SIZE_GROUPS in FE close-rate screen (prevents immediate crash).

2) Align CLOSE_RATE_METRICS in FE with BE (must include 'total').

3) Ensure scope button keys == _perf_close_rate_scope_members keys.
