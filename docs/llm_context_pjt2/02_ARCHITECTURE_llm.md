---
title: 아키텍처 (PJT2) – 카운터파티 리스크 리포트
last_synced: 2026-01-29
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
- DB 교체(일일 스냅샷)와 리포트 생성이 충돌하지 않도록 스냅샷 후 읽기-only로 집계한다.
- 리포트는 캐시 파일(`report_cache/YYYY-MM-DD.json`)을 우선 서빙하며, 없으면 생성 후 제공한다.
- LLM은 env 설정 시 OpenAI 호출, 미설정/실패 시 폴백 evidence/actions로 채운다. 프롬프트는 mode별 파일(`dashboard/server/agents/counterparty_card/prompts/{offline|online}/v1/*.txt`)을 사용한다.
- 프런트는 서버 응답을 그대로 쓰지 않고, **DRI override universe**를 클라이언트에서 적용한다: 출강은 `target26OfflineIsOverride` 전부(0 포함), 온라인은 `target26OnlineIsOverride` & `target26Online!=0` 전부를 로드해 리포트 row를 재구성·타겟 덮어쓰고 요약을 재계산한다(없던 키는 synthetic row로 추가).

## Invariants
- 입력 DB: salesmap_latest.db (SQLite). 없으면 500/오류.
- 스냅샷: report_scheduler가 DB 안정성 확인 후 `report_work/salesmap_snapshot_<as_of>_<HHMMSS>.db`로 복사.
- 캐시: offline `report_cache/{as_of}.json`, online `report_cache/counterparty-risk/online/{as_of}.json`; status `status.json`/`status_online.json` 보존.
- LLM 캐시: `report_cache/llm/{as_of}/{db_hash}/{mode}/{org}__{upper}.json` (`llm_input_hash`+prompt_version 일치 시 재사용).
- 스케줄: APScheduler cron(기본 "0 8 * * *", TZ=Asia/Seoul), REPORT_MODES로 모드 제어, ENABLE_SCHEDULER=0이면 main.py startup에서 start_scheduler 건너뜀.
- API: `/api/report/counterparty-risk` 캐시 우선 → 없으면 run_daily_counterparty_risk_job(force) → fallback last_success(meta.is_stale) → 없으면 500.
- 락: `report_cache/.counterparty_risk.lock` fcntl/msvcrt 겸용, 모드 루프 공용, 충돌 시 SKIPPED_LOCKED.
- 프런트 DRI 로딩: `loadTarget2026SourceRowsAll`로 size별 전체 DRI, override 조건 클라이언트 적용, 팀/파트 필터도 동일 DRI 인덱스 사용.
- 입력 DB: `salesmap_latest.db`(SQLite). 없는 경우 500/오류 상태.
- 스냅샷: 리포트 생성 시 DB를 `report_work/salesmap_snapshot_<as_of>_<HHMMSS>.db`로 복사 후 사용.
- 캐시: offline은 `report_cache/YYYY-MM-DD.json`, online은 `report_cache/counterparty-risk/online/YYYY-MM-DD.json`에 원자적 저장. status는 mode별(`status.json`, `status_online.json`)로 기록.
- LLM 캐시: `report_cache/llm/{as_of}/{db_hash}/{mode}/{org}__{counterparty}.json` (`llm_input_hash` 일치 시 재사용). counterparty_llm는 agent 어댑터로 위 경로를 사용한다.
- 스케줄: APScheduler cron(기본 "0 8 * * *", TZ=Asia/Seoul)에서 두 모드(off→on) 순차 실행. `ENABLE_SCHEDULER=0`이면 main.py startup 훅에서 start_scheduler가 건너뜀. `REPORT_MODES` env로 모드 리스트를 제어한다.
- API: `/api/report/counterparty-risk`는 mode 파라미터 기본 offline, 캐시 우선 → 없으면 생성(force) → fallback 최근 성공본(meta.is_stale=true).
- 락: `report_cache/.counterparty_risk.lock` (fcntl + Windows msvcrt), 모드 루프 전체에 공용 사용, 실패 시 SKIPPED_LOCKED 처리.
- 프런트 DRI 로딩: `loadCounterpartyRows(size)`를 limit 없이 호출해 size별 전체 DRI를 사용하며, 출강/온라인 각각 mode별 override 조건으로 universe를 강제한다. 팀→파트 매핑도 동일 DRI 전체를 사용한다.

## Recent Updates (frontend + matching)
- Daily Report V2(출강) 렌더러는 counterparty-risk-daily 메뉴에 매핑, DRI만으로 target/actual 5컬럼 테이블 후 row 클릭 시 `/api/llm/target-attainment` 호출.
- LLM target-attainment 엔드포인트는 payload 512KB 초과 시 413, debug=1일 때만 __meta를 추가한다.
- DRI 매칭: override/DRI 매칭은 org/upper 모두 trim한 exact match(`database.py`).
- Daily Report V2(출강): DRI 전체 row에서 target/actual만으로 5컬럼 테이블을 렌더하며, 행 클릭 시 `/api/llm/target-attainment`를 호출해 모달에 LLM JSON을 표시한다(`org_tables_v2.html`).
- Progress LLM(L1 가동): `progress_universe`에서 프런트와 동일한 universe(리포트 rows ∪ mode별 override rows)와 `actual_2026` 주입을 재현해 L1 입력을 생성하며, fallback(if-else) 포함 CounterpartyProgressAgent가 실 LLM/수리 프롬프트(v1)로 캐시(`report_cache/llm_progress/...`)를 채운다. 스케줄러는 06:00 KST에 오프라인→온라인 순으로 스냅샷 후 프리컴퓨트한다.

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
