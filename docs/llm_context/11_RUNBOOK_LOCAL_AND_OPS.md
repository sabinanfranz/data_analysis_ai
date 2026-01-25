---
title: 로컬/운영 런북
last_synced: 2026-12-11
sync_source:
  - dashboard/server/main.py
  - start.sh
  - org_tables_v2.html
  - salesmap_first_page_snapshot.py
absorbed_from:
  - user_guide.md
  - snapshot_pipeline.md
  - error_log.md
  - api_behavior.md
  - kpi_review_report.md
---

## Purpose
- 로컬 개발 및 운영 시 필요한 기동/환경 변수/캐시 동작을 코드 기준으로 정리한다.

## Behavioral Contract
- 로컬 실행:
  - 백엔드: `python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload`. `main.py`는 `DB_PATH`(기본 `salesmap_latest.db`)가 없으면 500을 반환한다.
  - 프런트: `python -m http.server 8001` 후 `http://localhost:8001/org_tables_v2.html` 열기(또는 파일 직접 열기). API_BASE는 origin+/api 또는 `http://localhost:8000/api`.
  - 가상환경: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`.
- 컨테이너/운영(start.sh):
  - 환경 변수: `DB_URL`(필수, 50MB 미만은 실패), `DB_ALWAYS_REFRESH`(기본 1), `PORT`(기본 8000).
  - 동작: DB 미존재 또는 항상 새로고침 시 Python 다운로더로 DB를 tmp→`/app/data/salesmap_latest.db` 저장 후 `/app/salesmap_latest.db`에 심볼릭 링크, `DB_PATH`를 세팅하고 `uvicorn dashboard.server.main:app` 실행.
- 스냅샷:
  - `salesmap_first_page_snapshot.py`로 DB 생성/교체, run_history.jsonl 기록, webform_history 후처리. `SALESMAP_TOKEN` 필수.
- 프런트 캐시: org_tables_v2는 fetch 결과를 Map에 저장하며 무효화가 없으므로 DB 교체 후 새로고침 필요.
### (흡수) 로컬 실행/PowerShell 절차
- 백엔드 기동: `python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload`. `main.py`는 `DB_PATH`(기본 `salesmap_latest.db`)가 없으면 `/api/*`가 500을 반환한다.
- 프런트 열기: 정적 서버로 `python -m http.server 8001` 실행 후 `http://localhost:8001/org_tables_v2.html` 접속(또는 파일 직접 열기). origin이 없으면 `API_BASE`는 `http://localhost:8000/api`로 강제된다.
- 가상환경/의존성: PowerShell에서 `python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt`. 실패하면 `.\.venv\\Scripts\\python.exe` 경로를 직접 지정해 실행한다.
- 스냅샷 실행 예시: `$env:SALESMAP_TOKEN=\"<토큰>\"; python .\\salesmap_first_page_snapshot.py --db-path .\\salesmap_latest.db --log-dir .\\logs --checkpoint-dir .\\logs\\checkpoints --backup-dir .\\backups --keep-backups 30`. 재개 시 `--resume` 또는 `--resume-run-tag`, webform-only 시 `--webform-only` 옵션만 실행하며 manifest/run_info를 덮어쓰지 않는다.

## Invariants (Must Not Break)
- DB 경로는 백엔드/프런트/컨테이너 모두 `salesmap_latest.db`를 기본으로 사용해야 한다.
- start.sh는 DB 다운로드 크기가 50MB 미만이면 오류로 중단한다.
- API_BASE 계산은 origin+/api 또는 `http://localhost:8000/api`로 고정이며, 포트/경로가 변경되면 HTML 수정을 동반한다.
- 스냅샷 실행은 토큰 미설정 시 종료하며, 교체 실패 시 폴백 DB 경로를 로그/run_history에 남긴다.

## Coupling Map
- 서버: `dashboard/server/main.py`, `dashboard/server/org_tables_api.py`, `dashboard/server/database.py`.
- 컨테이너: `start.sh`(DB 다운로드/링크/uvicorn).
- 프런트: `org_tables_v2.html`(API_BASE/캐시).
- 파이프라인: `salesmap_first_page_snapshot.py`(DB 생성/교체).
- 문서: `05_SNAPSHOT_PIPELINE_CONTRACT.md`, `06_API_CONTRACT_CORE.md`, `09_FRONTEND_ORG_TABLES_V2_CONTRACT.md`, `11_RUNBOOK_LOCAL_AND_OPS.md`(본 문서).

## Edge Cases & Failure Modes
- DB 잠금/부재 시 `/api/*`가 500을 반환한다. start.sh는 DB가 없으면 다운로드 후에도 실패 시 종료한다.
- 프런트를 파일로 직접 열면 origin이 null이라 API_BASE가 `http://localhost:8000/api`로 강제된다.
- Windows에서 체크포인트/DB 교체 rename이 실패하면 폴백 파일이 남아 FastAPI가 이전 DB를 계속 읽을 수 있다.
### (흡수) 캐시/스냅샷 운영 이슈
- API가 DB mtime 기반 메모리 캐시(`_COUNTERPARTY_DRI_CACHE`, `_PERF_MONTHLY_*`, `_PL_PROGRESS_*`, `_RANK_2025_SUMMARY_CACHE`)를 사용하므로 DB 교체 직후에는 FastAPI 재시작 또는 프런트 새로고침을 해야 최신 데이터가 반영된다.
- `salesmap_first_page_snapshot.py` 실행 중 WinError 32/5로 rename이 실패하면 `<dest_stem>_<run_tag>.db` 폴백이 남거나 `.json.tmp`가 복사되어 저장된다(복구 절차는 05_SNAPSHOT_PIPELINE_CONTRACT 참조).
- Counterparty Risk 리포트는 DB가 수정 중이면 `DB_STABLE_WINDOW_SEC` 내에서 실패를 기록하고 status.json을 남길 수 있어, 스냅샷 교체 직후에는 재시작/재계산이 필요하다.

## Verification
- 로컬에서 uvicorn 기동 후 `/api/health`가 ok, `/api/orgs` 호출이 성공하는지 확인한다.
- start.sh 실행 시 DB 다운로드가 50MB 이상이고 `/app/salesmap_latest.db` 심볼릭 링크가 생성되는지 확인한다.
- 스냅샷 실행 후 run_history.jsonl에 final_db_path가 기록되고 FastAPI가 해당 DB를 읽는지 확인한다.
- 프런트에서 메뉴 전환 시 `/api/*` 호출이 정상이고, 새 DB 교체 후 새로고침을 해야 최신 데이터가 표시되는지 확인한다.
### (흡수) 추가 검증 포인트
- PowerShell에서 `python -m http.server 8001`로 프런트를 열고 `/api/health`, `/api/orgs` 호출이 성공하는지 DevTools Network에서 확인한다.
- 스냅샷 실행 시 `$env:SALESMAP_TOKEN` 미설정이면 즉시 종료되는지, `--resume --resume-run-tag`로 재개 가능한지, `--webform-only`가 manifest/run_info를 덮어쓰지 않고 webform_history만 갱신하는지 spot-check한다.
- DB 교체 후 FastAPI 재시작/프런트 새로고침 없이 캐시된 응답이 남는지 확인해 운영 시 재시작 필요성을 체크한다.

## Refactor-Planning Notes (Facts Only)
 - DB 경로/API_BASE/포트가 코드 곳곳에 상수로 박혀 있어 운영 환경을 바꾸려면 start.sh, main.py, 프런트 HTML을 동시에 수정해야 한다.
 - 프런트 캐시 무효화가 없으므로 배포 시 사용자가 새로고침하지 않으면 이전 데이터를 볼 수 있다.
 - 스냅샷 교체 실패/체크포인트 실패 시 수동 조치가 필요하지만 자동 알림/모니터링은 없다.

### (부록) KPI Review Report(오프라인 단일 HTML) 생성/사용/불변조건/QA 체크리스트
#### Purpose
- 2025 성과평가용 개인 KPI 검수 리포트를 단일 HTML로 생성해 브라우저에서 팀/파트/개인별 KPI 계산·제외 흐름을 제공한다(Chunk 1~3 기준).
#### Behavioral Contract
- 생성: `python build_kpi_review_report.py --db <db> --out <path> --existing-orgs <file> --years 2024,2025` 실행 시 템플릿을 읽어 `window.__DATA__`에 JSON을 인라인 주입한 단일 HTML을 만든다.
- 데이터 추출: deal 테이블에서 Convert 상태 제거 후 `createdAt`/`contractDate` 연도가 years 리스트에 포함되면 포함한다(문자열 시작 `YYYY`). organization 조인 시 `"이름"` 우선, 없으면 organizationId→dealId 순 대체. net% 컬럼은 PRAGMA로 `netPercent→net→NET→net%→NET%→공헌이익률→공헌이익률(%)→공헌이익률 %` 순으로 탐지하며 없으면 `meta.netPercentColumn="__NONE__"`.
- UI: 상단 3단 필터(팀 → 파트/셀 → 개인). 팀/파트는 고정 ORG_MAP(기업교육 1팀/2팀 + 1/2파트/온라인셀)만 노출, 개인 Select 첫 옵션은 `ALL (해당 파트/셀 전체)`. ORG_MAP 밖 담당자 딜은 전처리에서 완전히 제외되어 화면/저장에 포함되지 않고 배지/메타에 `Filtered out (outside roster)`로 표시된다. person=ALL에서는 제외 편집 불가(읽기 전용 union 적용), 특정 개인 선택 시에만 편집/저장이 가능하다.
- 탭1 KPI 요약: 2024/2025 × 전체/온라인/비온라인 + Δ. 체결률은 리드연도 기준(Won/전체), 금액/공헌이익률/리텐션/업셀은 체결연도 Won 기준, 비온라인 공헌이익률은 net% 단순 평균, 온라인은 100%.
- 탭2 과정포맷 분석: 연도 토글(기본 2025), 과정포맷별 리드/체결 성과, 온라인 3종은 공헌이익률 100%.
- 탭3 딜 리스트: 팀/파트/개인 필터 후 Convert 제외, 제외 체크박스 제공(ALL에서는 편집 불가). 제외 시 KPI/과정포맷/탭4 즉시 갱신. 탭4 제외 내역은 현재 person 제외 리스트를 표시하고 개별 복구 가능(ALL은 복구 비활성). reason/note는 표시만 하고 빈 문자열로 export.
- Exclude/저장 규칙: `excludedSet=Set<dealId>`로 관리하며 KPI/포맷 계산에서 제외. localStorage 키는 `kpi_review::2024_2025::<dataGeneratedAt>::excludedDealIds::<personName>`(dataGeneratedAt 없으면 generatedAt)이며 저장/편집은 특정 개인에서만 허용, ALL은 현재 파트/셀 union excluded를 읽기만 한다. 팀/파트 변경 시 person은 자동으로 ALL로 리셋되고 해당 파트/셀 union excluded를 적용한다.
- Export/Import/초기화 버튼은 제거되었으며 제외 상태는 localStorage에 자동 저장/복원된다(개인 단위). 필요 시 직접 localStorage를 비우거나 키를 삭제한다.
#### Invariants (Must Not Break)
- HTML은 단일 파일이며 외부 fetch/CDN 없이 더블클릭으로 실행 가능해야 한다.
- Convert 상태는 모든 지표/리스트에서 제외된다.
- 체결률 분모는 전체 딜(Lead 기준), 금액/공헌이익률/리텐션/업셀은 체결연도 Won 기준이며 비온라인 공헌이익률은 net% 단순 평균(금액가중 금지), 온라인은 1.0(100%).
- localStorage 키 버전에 dataGeneratedAt을 포함해 DB 교체 시 이전 제외내역이 섞이지 않는다. `kpi_review::` prefix를 변경하면 안 된다.
- ALL(person=ALL) 모드는 제외 union 조회만 허용하며 편집은 개별 person에서만 허용된다.
- ORG_MAP에 없는 담당자 딜은 로딩 단계에서 완전히 제외되어야 하며, meta.filteredByOrgMapCount와 배지 `Filtered out (outside roster)`에 반영된다.
- net% 컬럼이 없으면 `meta.netPercentColumn="__NONE__"`로 기록되어야 한다.
#### Coupling Map
- 빌더/템플릿: `build_kpi_review_report.py`, `templates/kpi_review_report.template.html`.
- 입력 데이터: `salesmap_latest.db`(deal/organization), `data/existing_orgs_2025_eval.txt`.
- 결과물: CLI가 생성하는 단일 HTML(기본 파일명 `2025성과평가_개인KPI_검수용_<years>_<today>.html`), localStorage(`kpi_review::...`)에 제외 상태 저장.
#### Edge Cases & Failure Modes
- DB 경로/Existing orgs/템플릿 파일이 없으면 빌더가 예외로 중단된다.
- 필수 컬럼이 없으면 FriendlySchemaError로 시도한 후보+실제 컬럼을 안내하며 실패한다.
- 연도 파싱 실패/누락 건수는 meta에 기록되고 해당 딜은 연도 필터에 포함되지 않는다.
- ORG_MAP 밖 담당자 딜이 meta.filteredByOrgMapCount>0인데 화면/내보내기에 노출되지 않는지 확인해야 한다.
#### Verification
- `python build_kpi_review_report.py --db salesmap_latest.db --out /tmp/report.html` 실행 후 `/tmp/report.html`을 열어 탭1~4가 모두 노출되고 JS 오류가 없는지 확인한다.
- 팀/파트/개인 선택 후 딜 제외 체크 시 탭1/탭2 수치가 즉시 변경되는지, 새로고침 후 localStorage에서 제외 상태가 복원되는지 확인한다.
- ALL(person=ALL) 모드에서 체크박스/복구가 비활성 안내로 막히는지 확인한다.
- `meta.dealCountBeforeFilters`→Convert 필터→연도 필터 카운트가 실제 딜 수와 일치하는지 spot-check한다.
- net% 컬럼이 없는 DB에서 `meta.netPercentColumn="__NONE__"`인지, 있는 DB에서는 탐지된 컬럼명이 기록되는지 확인한다.
#### QA Checklist (필수)
- [ ] Convert 딜이 어디 표/리스트에도 보이지 않는가?
- [ ] 체결률 분모에 Lost/SQL 등이 포함되고 Won만 분모로 쓰지 않는가?
- [ ] 계약일 없는 Won 딜이 체결액/리텐션/업셀 계산에 섞이지 않는가?
- [ ] 비온라인 공헌이익률이 AVG(net%)로 계산되는가(금액가중 아님)?
- [ ] 온라인 3포맷 공헌이익률이 100%로 처리되는가?
- [ ] 딜 제외 체크 시 KPI/과정포맷 표가 즉시 변하는가?
- [ ] 새로고침해도 제외 상태가 복원되는가(localStorage)?
#### Refactor-Planning Notes (Facts Only)
- 컬럼 후보군이 코드 상수로만 존재해 새로운 DB 스키마 대응 시 후보 목록을 업데이트해야 한다.
- 제외 사유/메모는 현재 빈 문자열로만 export/import되므로 localStorage 스키마 변경이 필요하다.
- ALL 모드 편집은 의도적으로 제한되어 person별 저장 충돌을 방지한다.
