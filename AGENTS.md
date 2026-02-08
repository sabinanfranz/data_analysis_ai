# AGENTS.md

이 레포는 **Salesmap 스냅샷(SQLite) → FastAPI → 정적 단일 HTML(org_tables_v2.html)** 구조의 B2B 대시보드입니다.
Codex/에이전트가 작업할 때는 아래 규약(SSOT/불변조건/검증 절차)을 최우선으로 따릅니다.

---

## 1) 시스템 개요 (SSOT 우선)
- 데이터 수집/교체: `salesmap_first_page_snapshot.py`가 Salesmap API를 수집해 `salesmap_latest.db`에 적재/교체합니다.
- 백엔드: `dashboard/server/main.py`(엔트리) → `dashboard/server/org_tables_api.py`(라우터) → `dashboard/server/database.py`(집계/정렬/캐시/대부분의 로직).
- 프런트: `org_tables_v2.html` 단일 정적 파일이 `/api/*`를 fetch해서 화면을 렌더링하며, 화면별 Map 캐시를 가집니다(무효화 없음).
- 문서 SSOT: `docs/llm_context/*`(00~14), PJT2는 `docs/llm_context_pjt2/*`가 별도 SSOT입니다.

---

## 2) Single Source of Truth (SSOT) 규칙
작업 전/중/후에 **SSOT 문서와 코드가 충돌하지 않도록** 확인합니다.

- 아키텍처/책임 분리: `docs/llm_context/02_ARCHITECTURE.md`
- 기능↔파일 맵: `docs/llm_context/03_REPO_MAP.md`
- 로컬/운영 런북: `docs/llm_context/11_RUNBOOK_LOCAL_AND_OPS.md`
- 프런트 계약: `docs/llm_context/09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`
- 테스트/품질: `docs/llm_context/12_TESTING_AND_QUALITY.md`
- (PJT2) 카운터파티 리스크 리포트: `docs/llm_context_pjt2/*`

> 원칙: “코드/계약(SSOT) → 구현/테스트 → 문서(동기화)” 순서로 진실을 유지합니다.

---

## 3) 절대 깨면 안 되는 불변조건(요약)
아래는 변경 시 **프런트/백엔드/테스트/운영이 연쇄적으로 깨지기 쉬운** 핵심 축입니다.

- DB 경로는 기본 `salesmap_latest.db`(또는 `DB_PATH` env)로 통일됩니다.
- 프런트는 브라우저 메모리(Map) 캐시만 존재하며 **무효화가 없어서 DB 교체 후 새로고침이 필수**입니다.
- FastAPI는 가능한 무상태(thin)로 유지하고, **집계/정렬/캐시 로직은 database.py**에 집중되어 있습니다(라우터 비대화 금지).
- API 계약(파라미터/정렬/응답 스키마) 변경은 반드시 SSOT 문서와 테스트를 함께 갱신합니다.

---

## 4) 로컬 실행 / 빠른 검증 커맨드
### 백엔드
```bash
python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload
```

### 프런트(정적)
```bash
python -m http.server 8001
# http://localhost:8001/org_tables_v2.html
```

### 스냅샷 생성/교체
```bash
SALESMAP_TOKEN=... python salesmap_first_page_snapshot.py \
  --db-path salesmap_latest.db \
  --log-dir logs --checkpoint-dir logs/checkpoints --backup-dir backups --keep-backups 30
```

### 테스트
```bash
PYTHONPATH=. python -m unittest discover -s tests
node --test tests/org_tables_v2_frontend.test.js
```

---

## 5) 변경 작업 기본 원칙

* 리팩토링은 “외부 동작 유지 + 작은 단위 + 테스트/검증 동반”을 기본으로 합니다.
* 변경 범위를 최소화하고, 계약(문서/테스트)을 안전망으로 삼습니다.
* 프런트는 단일 HTML 파일이므로, 변경 시 영향 범위가 큽니다:
  * 상태/렌더/이벤트/캐시 변경은 프런트 계약과 JS 테스트(있다면)를 함께 확인합니다.
  * API 응답 필드/정렬이 바뀌면 반드시 화면별 렌더러가 깨질 수 있습니다.

---

## 6) Codex Skills 사용 규칙

이 레포는 repo-scoped skills를 `.agents/skills/*`에 둡니다.

* “지식 문서(마크다운)를 스킬로 패키징(SKILL.md + references/* + AGENTS.md 트리거 라인 업데이트)”하는 작업이 포함되면,
  **항상 `$skill-packager` 스킬을 호출**하고 그 절차/레퍼런스를 따릅니다.
