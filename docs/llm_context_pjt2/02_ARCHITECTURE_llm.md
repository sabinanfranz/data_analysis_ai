---
title: 아키텍처 (PJT2) – 카운터파티 리스크 리포트
last_synced: 2026-02-05
sync_source:
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
  - dashboard/server/agents/registry.py
  - dashboard/server/agents/core/orchestrator.py
  - dashboard/server/report/progress_universe.py
  - dashboard/server/report/composer.py
  - dashboard/server/report_scheduler.py
  - dashboard/server/org_tables_api.py
  - dashboard/server/main.py
  - org_tables_v2.html
---

# 아키텍처 (PJT2) – 카운터파티 리스크 리포트

## Purpose
- salesmap_latest.db를 입력으로 카운터파티 리스크 리포트를 생성·캐시·서빙하는 신규 컴포넌트를 기존 FastAPI/프런트 구조에 통합한 전반 흐름을 정의한다.

## Behavioral Contract
- FastAPI startup에서 `start_scheduler()`가 실행되어 cron(REPORT_CRON 기본 08:00 KST)으로 offline→online 순서 리포트를 생성한다. ENABLE_SCHEDULER=0이면 스케줄러는 기동하지 않는다.
- 보고서는 스냅샷 DB(`report_work/salesmap_snapshot_<as_of>_<HHMMSS>.db`)를 읽어 생성하며, 캐시(`report_cache/{as_of}.json` 또는 `report_cache/counterparty-risk/online/{as_of}.json`)를 우선 서빙한다. cache miss 시 force 생성 후 제공, 실패 시 last_success를 meta.is_stale로 폴백한다.
- LLM은 env(LLM_PROVIDER=openai + OPENAI_API_KEY) 설정 시 OpenAI ChatCompletions, 미설정/실패 시 fallback evidence/actions를 사용한다. 프롬프트는 mode별 `agents/counterparty_card/prompts/{mode}/v1/*.txt`.
- 프런트는 응답을 클라이언트 측 DRI override universe에 투영한다: 출강은 target26OfflineIsOverride 전체(0 포함), 온라인은 target26OnlineIsOverride & target26Online!=0 전체를 사용해 target을 덮어쓰고 summary를 재계산, 누락된 카운터파티는 synthetic row로 추가한다.

## Invariants
- 입력 DB: `salesmap_latest.db`(SQLite). 없음/불안정 시 FileNotFoundError/DB_UNSTABLE_OR_UPDATING.
- 스냅샷: report_scheduler가 DB 안정성(최종 mtime ≥ 180s) 확인 후 `report_work/salesmap_snapshot_<as_of>_<HHMMSS>.db`로 복사.
- 캐시: offline `report_cache/{as_of}.json`, online `report_cache/counterparty-risk/online/{as_of}.json`; status 파일(status.json/status_online.json) 보존.
- LLM 캐시: `report_cache/llm/{as_of}/{db_hash}/{mode}/{org}__{counterparty}.json` (llm_input_hash+prompt_version 일치 시 재사용).
- 메타 필드: report 생성 시 meta에 db_version(입력 DB mtime ISO), db_signature(mtime-size), generator_version=d7-v1, job_run_id(YYYYMMDD_HHMMSS) 포함.
- 스케줄: APScheduler cron(기본 \"0 8 * * *\", TZ=Asia/Seoul), REPORT_MODES로 모드 제어, ENABLE_SCHEDULER=0이면 startup 훅에서 start_scheduler 스킵. PROGRESS_CRON/ENABLE_PROGRESS_SCHEDULER로 progress L1 사전계산 별도 제어.
- API: `/api/report/counterparty-risk` 캐시 우선 → 없으면 run_daily_counterparty_risk_job(force) → last_success 폴백(meta.is_stale) → 없으면 500.
- 락: `report_cache/.counterparty_risk.lock` (fcntl + Windows msvcrt) 공용, 충돌 시 SKIPPED_LOCKED.
- 프런트 DRI 로딩: `loadTarget2026SourceRowsAll`로 size별 전체 DRI를 불러와 override 조건을 적용해 universe/target을 재계산, 팀/파트 인덱스도 동일 DRI 기반.

## Recent Updates (frontend + matching)
- Daily Report V2(출강) 렌더러는 counterparty-risk-daily 메뉴에 매핑, DRI만으로 target/actual 5컬럼 테이블 후 row 클릭 시 `/api/llm/target-attainment` 호출.
- LLM target-attainment 엔드포인트는 payload 512KB 초과 시 413, debug=1일 때만 __meta를 추가한다.
- DRI 매칭: override/DRI 매칭은 org/upper 모두 trim한 exact match(`database.py`).
- Daily Report V2(출강): DRI 전체 row에서 target/actual만으로 5컬럼 테이블을 렌더하며, 행 클릭 시 `/api/llm/target-attainment`를 호출해 모달에 LLM JSON을 표시한다(`org_tables_v2.html`).
- Progress LLM(L1): build_progress_universe → build_l1_payload로 생성된 payload를 CounterpartyProgressAgent가 실행, 결과는 `report_cache/llm_progress/{as_of}/{db_hash}`에 저장하며 PROGRESS_CRON(기본 06:00)에서 offline→online 순으로 스냅샷 후 실행된다.

## Coupling Map
- Generator/Rules: `dashboard/server/deal_normalizer.py` (D1~D5) + Orchestrator/Composer 병합.
- Agents: `dashboard/server/agents/registry.py`(report_id×mode→agent chain), `agents/core/orchestrator.py`, `agents/counterparty_card/*`(LLM/fallback), `counterparty_llm.py`(어댑터).
- Cache/Snapshot/Scheduler: `dashboard/server/report_scheduler.py` (+ start_scheduler in `main.py`).
- API: `dashboard/server/org_tables_api.py` (`/report/counterparty-risk`, `/recompute`, `/status` mode 지원).
- 프런트: `org_tables_v2.html` 메뉴/렌더(`counterparty-risk-daily`→“2026 Daily Report(출강)”, `counterparty-risk-daily-online`→“2026 Daily Report(온라인)”).

## Edge Cases
- DB 교체 직후(3분 이내) 스케줄 실행 시 재시도 후 실패 가능 → status에 FAILED, 캐시는 최근 성공본 유지.
- LLM 호출 실패/미연동 시 폴백 evidence/actions로 `SUCCESS_WITH_FALLBACK` 처리(보고서 생성은 계속).
- 캐시 쓰기 실패 시 기존 캐시 유지, status에 CACHE_WRITE_FAILED 기록 필요(보고서 미생성).

## Verification
- 스냅샷 경로 생성/사용 여부 확인: report_scheduler `_make_snapshot`.
- 캐시 파일 생성/내용(meta.as_of/db_signature)이 리포트 JSON에 존재하는지 확인.
- API 호출 시 캐시가 반환되는지, 캐시 없으면 생성 후 반환되는지 수동 호출로 검증.
- LLM 캐시: 동일 입력으로 두 번 실행 시 `report_cache/llm/{as_of}/{db_hash}/{mode}/...`이 재사용되는지 해시 비교.

## Refactor-Planning Notes (Facts Only)
- FastAPI startup에서 `load_dotenv()`와 `start_scheduler()`를 호출하므로 배포 환경이 변하면 main.py 수정이 필요한 지점이다.
- DB 해시는 report_scheduler에서 mtime 기반 문자열에 sha256을 적용해 16자 prefix로 쓰며, 캐시/LLM 폴더 구조가 이 값에 종속되어 있다.
- TEMP 테이블(deal_norm 등)은 build_counterparty_risk_report 내부 커넥션 스코프에만 존재하므로 커넥션 분리/병렬화 시 스코프 누락 회귀에 주의해야 한다.

## Diagram
```mermaid
flowchart LR
  DB[salesmap_latest.db] -->|copy| SNAP[salesmap_snapshot_<as_of>_<HHMMSS>.db]
  SNAP --> GEN[build_counterparty_risk_report<br/>(deal_norm→tier→target→risk→LLM merge)]
  GEN --> CACHE[report_cache/YYYY-MM-DD.json]
  GEN --> LLMC[report_cache/llm/{as_of}/{db_hash}/...]
  CACHE --> API[/api/report/counterparty-risk/]
  API --> FRONT[org_tables_v2.html<br/>counterparty-risk-daily<br/>\"2026 Daily Report(WIP)\"]
  subgraph Scheduler
    CRON[cron 08:00 KST<br/>ENABLE_SCHEDULER=1] --> GEN
  end
```
