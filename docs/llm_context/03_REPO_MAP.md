# 레포 지도(기능 ↔ 파일)

LLM이 “어느 기능이 어느 파일에 있는지”를 빠르게 찾도록 핵심 트리와 역할을 요약했습니다.

## Top-level 트리(핵심만)
- `dashboard/server/` → FastAPI 백엔드 (DB 조회/집계, 라우터)
- `org_tables_v2.html` → 조직/People/Deal 뷰어(프런트, 정적 HTML+JS)
- `salesmap_first_page_snapshot.py` → Salesmap API 스냅샷 + 웹폼 수집
- `build_org_tables.py` → 정적 HTML 생성 스크립트(구버전 레이아웃)
- `docs/` → 사용/아키텍처/LLM 컨텍스트 문서
- `tests/` → Python 단위 테스트(웹폼/메모/JSON 등)
- `salesmap_latest.db` → 기본 SQLite 스냅샷 DB

## 핵심 파일 책임 표
| 파일 | 역할 | 주요 함수·엔드포인트 | 참고 문서 |
| --- | --- | --- | --- |
| `dashboard/server/main.py` | FastAPI 앱/라우터 등록, CORS 설정 | `/api/*` 라우터 포함 | `docs/api_behavior.md`, `docs/llm_context/02_ARCHITECTURE.md` |
| `dashboard/server/org_tables_api.py` | API 라우터 집합 | `/api/orgs`, `/api/orgs/{id}/won-groups-json`, `/api/rank/*` | `docs/api_behavior.md` |
| `dashboard/server/database.py` | DB 조회/집계, 메모/webform 정제 | `list_organizations`, `get_won_groups_json`, `get_won_summary_by_upper_org`, `get_rank_*`, `_clean_form_memo` | `docs/api_behavior.md`, `docs/json_logic.md` |
| `org_tables_v2.html` | 프런트 렌더/캐시, JSON/모달/UX | fetch helpers, `render*`, `loadWonGroupJson`, webform/메모 모달 | `docs/org_tables_v2.md`, `docs/json_logic.md` |
| `salesmap_first_page_snapshot.py` | Salesmap API 스냅샷/웹폼 적재, 체크포인트/백업 | `main()`, `CheckpointManager`, webform_history 후처리 | `docs/snapshot_pipeline.md` |
| `build_org_tables.py` | 정적 org_tables.html 생성(구 레이아웃) | CLI 엔트리, HTML 생성 | `docs/org_tables_usage.md` |
| `docs/llm_context/*.md` | LLM용 컨텍스트(인덱스/아키텍처/지도 등) | - | `docs/llm_context/00_INDEX.md` |
| `tests/test_won_groups_json.py` | webform 날짜 매핑/메모 정제/JSON 테스트 | `build_sample_db`, 단위 테스트 2종 | `docs/json_logic.md` |
| `docs/api_behavior.md` | API 동작/필터/정제 요약 | - | - |
| `docs/org_tables_v2.md` | 프런트 UX/화면 흐름/버튼 상태 | - | - |
| `docs/snapshot_pipeline.md` | 스냅샷 동작/교체/재개 절차 | - | - |

## 자주 수정하는 시나리오와 수정 포인트
- **API 추가/변경**:  
  - `dashboard/server/database.py`에 쿼리/집계 추가 → `org_tables_api.py`에 라우터 추가 → 필요 시 `docs/api_behavior.md` 갱신 → 프런트 fetch/render(`org_tables_v2.html`) 연동.
- **프런트 메뉴/UX 변경**:  
  - `org_tables_v2.html`의 상태/렌더 함수 수정, 버튼/모달 추가 → 관련 문서 `docs/org_tables_v2.md` 업데이트.
- **상위 조직 JSON/메모 정제 변경**:  
  - 로직은 `database.py#get_won_groups_json`, `_clean_form_memo`에서 수정 → `docs/json_logic.md`, `tests/test_won_groups_json.py` 갱신.
- **스냅샷 옵션/웹폼 수집 변경**:  
  - `salesmap_first_page_snapshot.py` 수정(옵션/체크포인트/백업) → `docs/snapshot_pipeline.md`에 절차 반영.
- **정적 HTML 생성(구 레이아웃)**:  
  - `build_org_tables.py` 수정 → `docs/org_tables_usage.md` 참고.

### 참고
- 조직 목록은 People 또는 Deal이 1건 이상 있는 조직만 반환하며, 2025년 Won 금액 내림차순 정렬(이름 순 보조).
- 프런트 캐시는 클라이언트 메모리(Map) 기반이며 무효화가 없으므로 DB 교체 시 새로고침이 필요합니다.
