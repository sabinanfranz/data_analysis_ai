---
title: 아키텍처 (PJT2) – 카운터파티 리스크 리포트
last_synced: 2026-01-06
sync_source:
  - dashboard/server/deal_normalizer.py
  - dashboard/server/counterparty_llm.py
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
- LLM은 env 설정 시 OpenAI 호출, 미설정/실패 시 폴백 evidence/actions로 채운다. 프롬프트는 파일(`dashboard/server/prompts/*.txt`)이 있으면 사용, 없으면 기본 상수 사용.

## Invariants
- 입력 DB: `salesmap_latest.db`(SQLite). 없는 경우 500/오류 상태.
- 스냅샷: 리포트 생성 시 DB를 `report_work/salesmap_snapshot_<as_of>_<HHMMSS>.db`로 복사 후 사용.
- 캐시: `report_cache/YYYY-MM-DD.json`에 원자적 저장. status.json으로 마지막 성공/실패 기록.
- LLM 캐시: `report_cache/llm/{as_of}/{db_hash}/{org}__{counterparty}.json` (`llm_input_hash` 일치 시 재사용).
- 스케줄: APScheduler cron(기본 "0 8 * * *", TZ=Asia/Seoul). `ENABLE_SCHEDULER=0`이면 startup에서 start_scheduler가 건너뜀.
- API: `/api/report/counterparty-risk`는 캐시 우선 → 없으면 생성(force) → fallback 최근 성공본.
- 락: `report_cache/.counterparty_risk.lock` (fcntl + Windows msvcrt), 실패 시 SKIPPED_LOCKED 처리.

## Coupling Map
- Generator/Rules: `dashboard/server/deal_normalizer.py` (D1~D6 + 리포트 빌더).
- LLM payload/canonical/hash/폴백: `dashboard/server/counterparty_llm.py` + 프롬프트 파일.
- Cache/Snapshot/Scheduler: `dashboard/server/report_scheduler.py` (+ start_scheduler in `main.py`).
- API: `dashboard/server/org_tables_api.py` (`/report/counterparty-risk`, `/recompute`, `/status`).
- 프런트: `org_tables_v2.html` 메뉴/렌더(`counterparty-risk-daily` → “2026 Daily Report”).

## Edge Cases
- DB 교체 직후(3분 이내) 스케줄 실행 시 재시도 후 실패 가능 → status에 FAILED, 캐시는 최근 성공본 유지.
- LLM 호출 실패/미연동 시 폴백 evidence/actions로 `SUCCESS_WITH_FALLBACK` 처리(보고서 생성은 계속).
- 캐시 쓰기 실패 시 기존 캐시 유지, status에 CACHE_WRITE_FAILED 기록 필요(보고서 미생성).

## Verification
- 스냅샷 경로 생성/사용 여부 확인: report_scheduler `_make_snapshot`.
- 캐시 파일 생성/내용(meta.as_of/db_signature)이 리포트 JSON에 존재하는지 확인.
- API 호출 시 캐시가 반환되는지, 캐시 없으면 생성 후 반환되는지 수동 호출로 검증.
- LLM 캐시: 동일 입력으로 두 번 실행 시 `report_cache/llm/...`이 재사용되는지 해시 비교.

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
  API --> FRONT[org_tables_v2.html<br/>counterparty-risk-daily<br/>\"2026 Daily Report\"]
  subgraph Scheduler
    CRON[cron 08:00 KST<br/>ENABLE_SCHEDULER=1] --> GEN
  end
```
