# 2026 체결률 현황 계약 감사 보고서

- 생성시각: 2026-02-03T01:48:36.908120Z

## Executive Summary

- FAIL: 0 / 11 항목


## SSOT Tables

- FE CLOSE_RATE_COURSE_GROUPS: ['구독제(온라인)', '선택구매(온라인)', '포팅', '오프라인'] (line 2314)

- BE CLOSE_RATE_COURSE_GROUPS: ['구독제(온라인)', '선택구매(온라인)', '포팅', '오프라인'] (line 167)

- FE CLOSE_RATE_METRICS: ['total', 'confirmed', 'high', 'low', 'lost', 'close_rate'] (line 2315)

- BE CLOSE_RATE_METRICS: ['total', 'confirmed', 'high', 'low', 'lost', 'close_rate'] (line 168)

- FE scope keys: ['all', 'corp_group', 'edu1', 'edu2', 'edu1_p1', 'edu1_p2', 'edu2_p1', 'edu2_p2', 'edu2_online'] (line 2324)

- BE scope keys: ['all', 'corp_group', 'edu1', 'edu2', 'edu1_p1', 'edu1_p2', 'edu2_p1', 'edu2_p2', 'edu2_online'] (line None)

- FE size groups (defined?): ['대기업', '중견기업', '중소기업', '공공기관', '대학교', '기타', '미기재'] (uses: 5)

- BE size groups: ['대기업', '중견기업', '중소기업', '공공기관', '대학교', '기타', '미기재']


## Contract Diff


## API Contract Check

- FE summary params: ['from', 'to', 'cust', 'scope']
- BE summary params: ['from_month', 'from', 'to_month', 'to', 'cust', 'scope']

- FE deals params: ['segment', 'row']
- BE deals params: ['segment', 'row', 'month', 'cust', 'scope', 'course', 'metric']


## Risk Hotspots


## Next Fix Order

1) Define or remove INQUIRY_SIZE_GROUPS in FE close-rate screen (prevents immediate crash).

2) Align CLOSE_RATE_METRICS in FE with BE (must include 'total').

3) Ensure scope button keys == _perf_close_rate_scope_members keys.
