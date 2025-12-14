# 테스트 & 품질 가이드

## 1) Python 테스트
- 실행 전: `PYTHONPATH=.` 설정이 필요하다(루트 기준).
- unittest 예시:  
  ```bash
  PYTHONPATH=. python3 -m unittest discover -s tests
  ```
- 단일 파일:  
  ```bash
  PYTHONPATH=. python3 -m unittest tests.test_won_groups_json
  ```
- pytest를 쓸 경우(로컬 venv에 설치 시):  
  ```bash
  PYTHONPATH=. pytest
  ```

## 2) 프런트 테스트
- 별도 패키지 매니저 스크립트는 없지만 Node 내장 테스트로 스모크를 돌릴 수 있다.
- `org_tables_v2.html` 주요 렌더/StatePath/툴팁 동작을 `node --test tests/org_tables_v2_frontend.test.js`로 실행(로컬 Node 필요).

## 3) 테스트 커버리지(핵심 영역)
- `test_won_groups_json.py`: 웹폼 날짜 매핑, 메모 정제 규칙 검증.
- `test_salesmap_first_page_snapshot.py`: 스냅샷 파이프라인 동작(체크포인트/백업 등) 검증.
- `test_mismatched_deals_2025.py`, `test_rank_2025_deals_people.py`, `test_won_totals_by_size.py`: 랭킹/집계 로직 검증.
- `test_build_org_tables.py`, `test_build_org_mindmap.py`: 정적 HTML/마인드맵 생성 로직 검증.
- `org_tables_v2_frontend.test.js`: 프런트 렌더/StatePath 메뉴/용어 모달 스모크(node --test).
- `test_statepath_engine.py`: StatePath 버킷/경로/추천 로직 및 딜 폴백 검증.
- `test_api_statepath_portfolio.py`: `/api/statepath/portfolio-2425` 응답 스키마/필터/금액 유형 검증.
- `test_won_summary.py`: `/won-summary`의 owners2025 포함 여부 검증.

## 4) 변경 유형별 권장 실행
- **API/쿼리/정제 로직 변경**: `PYTHONPATH=. python3 -m unittest tests.test_won_groups_json tests.test_won_totals_by_size tests.test_mismatched_deals_2025 tests.test_rank_2025_deals_people`
- **스냅샷 파이프라인 변경**: `PYTHONPATH=. python3 -m unittest tests.test_salesmap_first_page_snapshot`
- **정적 HTML 생성 변경**: `PYTHONPATH=. python3 -m unittest tests.test_build_org_tables tests.test_build_org_mindmap`
- **프런트 로직 변경**: 수동 브라우저 검증 + (Node 환경이 있다면) `node --test tests/org_tables_v2_frontend.test.js`

## 5) 수동 품질 체크리스트
- DB 교체 후 프런트 새로고침(캐시 무효화 없음).
- 조직 목록 정렬/필터 확인: People/Deal 연결 없는 조직이 목록에 보이지 않는지, 2025 Won desc 정렬 유지되는지.
- 상위 조직 JSON/웹폼 모달: 날짜/이름 표시, 버튼 활성 조건 확인.
- 스냅샷 실패 시: `backups/`, `logs/checkpoints/`, `logs/run_info/manifest` 유무 확인 후 `--resume` 여부 판단.
