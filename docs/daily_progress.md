# 2025-12-09 작업 기록

- org_tables_v2 상위 조직 JSON UX 보완
  - 회사 전환/로딩/에러 시 Won JSON 상태 초기화 + 복사 버튼 비활성화, 정상 로드 시만 활성화.
  - CSS 파서 오류를 유발하던 JS 위치를 수정해 진단 경고 해소.
- 문서 업데이트
  - `docs/org_tables_v2.md`에 JSON 카드 최신 동작(버튼 비활성/상태 초기화)과 venv+PYTHONPATH 테스트 방법 추가.
- 테스트
  - `.venv` 생성 후 `PYTHONPATH=. .venv/bin/pytest -q` (14/14 통과).
  - pytest가 없던 환경에서 venv로 설치하여 실행.

# 2025-01-07 작업 기록

- `build_org_tables.py` UI/로직 대규모 개편
  - People(딜 있음/딜 없음) 세트 분리, 각 세트에 Deal + People 메모(상) + Deal 메모(하) 스택 배치.
  - 상단 회사 메모 컨테이너: 메모 없으면 낮은 높이, 메모 있으면 중·하단 컨테이너 대비 절반 높이로 확장.
  - 기업 규모 필터 드롭다운 추가(기본: 대기업) → 회사 리스트 필터 후 조직 선택 드롭다운 갱신.
  - 금액 억 단위(소수 2자리), 날짜 YYYY-MM-DD 포맷 적용.
  - 듀얼 상태(stateWith/stateWithout) 관리로 두 세트 독립 동작, 선택 초기화 시 모두 리셋.
- 데이터 매핑 강화
  - 조직 데이터에 `기업 규모` 포함, org 옵션에 size 추가.
  - 조직 필터: people·deal 모두 없는 조직 제외 유지.
- 문서 추가/정리
  - `docs/org_tables_usage.md` 신설: org_tables.html 생성/사용법, 레이아웃, 동작 설명.
- 검증
  - `python3 -m unittest discover -s tests` (14/14 통과)
  - `python3 build_org_tables.py --output org_tables.html` 로 최신 HTML 생성 확인.

- org_tables API 연동/UX 보강 (유저/팀)
  - 헤더에 API Base/토큰 입력 + 새로고침 버튼 추가, 상태 배지로 로딩/에러 표시.
  - `/v2/user`, `/v2/team` 병렬 호출 + 백오프, 유저/팀 표 렌더(팀 구성원은 유저 이름과 매핑).
  - 기업 규모 드롭다운 실제 필터 적용(대기업 기본, 없을 때 전체로 폴백).
  - 회사 메모 카드 높이 자동 조절(has-memos), 회사 선택 없을 때 힌트 노출.
  - CLI/env 옵션 추가: `--api-base-url`, `--api-token`(`API_BASE_URL`, `API_TOKEN`).
  - 유닛 테스트 추가: API config HTML 임베드 검증.

# 2025-12-10 작업 기록

- Salesmap 스냅샷 복원력 개선
  - 체크포인트 저장 시 Windows 권한/잠금으로 rename 실패하면 최대 3회 재시도 후 tmp→본 파일 복사 폴백을 추가하여 크래시 방지(`CheckpointManager.save_table`).
  - 수동 복구 절차: 최신 `.tmp`를 `.json`으로 덮어쓰는 백업+교체 명령을 수행.
- 실행 가이드 보강
  - `docs/user_guide.md`에 PowerShell 한 줄 실행/재개 예시(`--resume`, `--resume-run-tag`) 추가.
- 재개 시도 메모
  - venv를 생성해 의존성 설치 후 재개 실행; Windows Python 경로에서는 venv 스크립트 인식 문제가 있어 WSL bash 경유 실행/토큰 설정 안내.

# 2025-12-11 작업 기록

- org_tables_v2 메뉴 확장/UX 개선
  - 상위 조직 JSON 카드를 단일 카드 좌/우 영역으로 통합, 모달 기반 보기/복사 버튼 2종으로 변경. 선택 초기화 시 규모/검색/회사까지 기본값으로 리셋하고 목록 재조회.
  - Salesmap 워크스페이스 링크 정규식 오류 수정으로 파싱 실패(파란 화면) 해결.
  - People 그룹 2025 뷰: 필터(규모/회사/상위 조직) + 딜 보기 모달 + 미입력 상위 조직/팀 행 제외 반영.
  - 고객사 불일치 뷰 추가: 딜 orgId ≠ People.organizationId 탐지, 규모별 캐시, 조직 이동/외부 링크 지원.
- 백엔드/스크립트
  - `/api/rank/2025-deals-people` 집계(2025 Won 조직의 People 그룹 + 모든 딜)와 `/api/rank/mismatched-deals` 추가.
  - People 웹폼 ID 유니크 카운트 도구 추가(`analyze_sequence_ids.py`), salesmap_latest.db 기준 고유 ID 199개.
- 문서/테스트
  - `docs/org_tables_v2.md` 최신 메뉴/UX/API 반영. 프런트 테스트 업데이트(`org_tables_v2_frontend.test.js`), node --test 통과 확인.
