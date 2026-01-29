## QA Checklist — Daily Report V2 (출강) & Target Attainment LLM

### 화면 스모크
- 사이드바 → `2026 Daily Report(출강)` 진입 시 테이블이 로드되는지 확인.
- 임의 row 클릭 → 모달이 즉시 열리고 `{loading:true}` → LLM/에러 JSON으로 갱신되는지 확인.
- 같은 row를 연타해도 네트워크 중복 호출 없이 캐시/락으로 바로 표시되는지 확인.
- upperOrg 매칭 실패 상황에서는 `{error:"UPPER_GROUP_NOT_FOUND"}` JSON이 모달에 노출되는지 확인.

### API 스모크
- `POST /api/llm/target-attainment?debug=1` 샘플 호출 시 응답에 `__meta`(input_hash, payload_bytes 등) 포함 여부 확인.
- 600KB 수준의 큰 `won_group_json_compact`로 호출 시 `413`과 `{"error":"PAYLOAD_TOO_LARGE"}` JSON이 반환되는지 확인.

### 테스트
- `python -m unittest discover -s tests` 실행하여 단위 테스트 통과 여부 확인.***
