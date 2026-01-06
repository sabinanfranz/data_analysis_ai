---
title: Salesmap Snapshot Pipeline
last_synced: 2026-01-06
sync_source:
  - salesmap_first_page_snapshot.py
  - logs/run_history.jsonl
  - docs/error_log.md
  - docs/llm_context/05_SNAPSHOT_PIPELINE_CONTRACT.md
---

## Purpose
- `salesmap_first_page_snapshot.py`가 Salesmap API 데이터를 SQLite로 적재·갱신하는 실제 흐름과 복구 규칙을 기록한다.

## Behavioral Contract
- **토큰/설정**: `SALESMAP_TOKEN` 필수. CLI 옵션으로 `--db-path`(기본 `salesmap_latest.db`), `--log-dir`(`logs`), `--checkpoint-dir`(`logs/checkpoints`), `--backup-dir`(`backups`), `--keep-backups`(기본 30), `--checkpoint-interval`(기본 50), `--resume`/`--resume-run-tag`, `--webform-only`를 받는다. `DEFAULT_BASE_URL`은 `https://salesmap.kr/api/v2`.
- **실행 흐름**:
  1) 로그 초기화(`setup_logging`), 필요 시 백업 생성(`maybe_backup_existing_db`).
  2) 체크포인트 로드(`CheckpointManager`), temp DB(`.tmp`) 준비. resume 시 기존 temp 경로 유지, 없으면 새 tmp 생성.
  3) paginated 엔드포인트(`/organization`, `/people`, `/deal`, `/lead`, `/memo`)를 `TableWriter`로 스트리밍 적재하며 N페이지마다 체크포인트 저장; single 엔드포인트(`/user`, `/team`)는 단건 호출로 적재.
  4) 완료 후 manifest/run_info를 SQLite(`manifest`, `run_info` 테이블)와 로그 파일에 기록하고 `finalize_sqlite_connection`으로 WAL 체크포인트/optimize를 수행한다.
  5) `replace_file_with_retry`로 tmp→최종 DB 교체(최대 5회, 실패 시 폴백 rename/copy 경로 기록). 교체 성공 여부와 백업·로그·최종 경로를 `logs/run_history.jsonl`에 append한다.
  6) 웹폼 후처리: `update_webform_history`가 deal.peopleId 기반 허용 People ID 집합에만 `/v2/webForm/<id>/submit`를 호출해 `webform_history` 테이블을 갱신한다.
- **재시도/백오프**: SalesmapClient는 요청 전 최소 interval(0.12s)을 보장하고, 429는 `Retry-After` 또는 지수 백오프(기본 10s)로 재시도, 5xx/네트워크 오류도 지수 백오프 후 최대 3회까지 재시도한다.
- **데이터 정규화**: `TableWriter`가 batch마다 새 컬럼을 자동 추가하고, memo/webform payload를 그대로 TEXT로 저장한다. JSON decode 실패 등은 `_serialize_value`로 문자열화한다.

## Invariants (Must Not Break)
- 기본 경로: DB=`salesmap_latest.db`, 로그=`logs/`, 체크포인트=`logs/checkpoints`, 백업=`backups/`를 사용한다(옵션 미지정 시). `MIN_INTERVAL=0.12`, `MAX_RETRIES=3`, `BACKOFF_429=10.0`.
- 백업은 기존 DB가 있을 때만 생성하며 `--no-backup`이 아니면 gzip으로 압축, 보관 개수는 `--keep-backups`로 제어한다.
- 체크포인트는 `<checkpoint_dir>/checkpoint_<run_tag>.json.tmp`로 작성 후 rename; rename 실패 시 최대 3회 재시도 후 tmp→본 파일 복사로 폴백한다.
- tmp→본 DB 교체는 최대 5회 `os.replace`; 모두 실패하면 `<stem>_<run_tag>.db`로 rename/copy 폴백하고 로그에 남긴다(`replace_file_with_retry`).
- `--webform-only` 실행 시 스냅샷 크롤 없이 webform_history만 갱신하며 run_info/manifest를 덮어쓰지 않는다.
- `run_history.jsonl`에는 run_tag, final_db_path, backup_path, manifest 테이블별 row/col, 오류 개수가 항상 기록된다.

## Coupling Map
- 스크립트: `salesmap_first_page_snapshot.py`(SalesmapClient, TableWriter, CheckpointManager, replace_file_with_retry, update_webform_history).
- 로그/체크포인트/백업 산출물: `logs/`, `logs/checkpoints/`, `backups/`, `logs/run_history.jsonl`.
- 장애 대응 기록: `docs/error_log.md`가 최근 잠금/rename 실패 사례를 다룬다.
- API 소비처: 생성된 SQLite를 FastAPI(`dashboard/server/main.py`, `database.py`)와 프런트(`org_tables_v2.html`)가 바로 읽는다.

## Edge Cases & Failure Modes
- DB 잠금으로 `os.replace`가 연속 실패하면 폴백 DB가 `<stem>_<run_tag>.db`에 남고 최종 경로는 기존 DB로 유지된다(로그/히스토리에 경로 기록). psutil이 있으면 잠금 프로세스를 경고로 남긴다.
- 체크포인트 rename 권한 오류 발생 시 tmp→복사 폴백 후 계속 진행하며, 수동 복구는 `.json.tmp`를 `.json`으로 복사한 뒤 `--resume` 실행이다.
- `SALESMAP_TOKEN` 미설정 시 즉시 종료한다. 429/5xx/네트워크 실패가 `MAX_RETRIES`를 초과하면 `max_retries_exceeded`로 중단되고 manifest에 오류가 남는다.
- resume 시 체크포인트 row_count와 실제 테이블 row_count가 다르면 경고만 찍고 계속 진행한다.
- webform_history 테이블이 없거나 peopleId/webFormId가 비어 있으면 해당 제출은 건너뛰고 dropped 카운트를 로그에 남긴다.

## Verification
- `$env:SALESMAP_TOKEN="..."; python .\salesmap_first_page_snapshot.py --db-path .\salesmap_latest.db --log-dir .\logs` 실행 후 `logs/run_history.jsonl`에 final_db_path/backup_path/row·col 정보가 추가되는지 확인한다.
- temp DB 교체 실패 상황을 시뮬레이션하여 `replace_file_with_retry`가 폴백 경로를 기록하고 로그에 경고를 남기는지 확인한다.
- 체크포인트 `.json`이 주기적으로 생성되고 rename 실패 시 `.tmp`가 복사돼 저장되는지, `--resume --resume-run-tag <tag>`로 이어서 실행되는지 확인한다.
- `--webform-only` 실행 후 기존 DB의 `webform_history` 테이블 row 수가 증가하고 다른 테이블(organization/deal 등)이 변경되지 않는지 spot-check한다.
- 429/5xx 응답이 반복될 때 재시도 후 `max_retries_exceeded`로 종료되고 manifest 오류/히스토리가 남는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 백업/로그/체크포인트 경로와 DB 파일명이 코드 상수로 중복 정의되어 있어 환경별 분기나 설정 파일 없이 변경하기 어렵다.
- replace_file_with_retry/CheckpointManager의 폴백 로직이 Windows 잠금 대응에 의존적이며, 동일 로직이 다른 스크립트에는 없다.
- webform 후처리가 스냅샷 완료 후에만 실행되고 실패해도 예외를 무시하므로 webform_history의 최신성이 run_history에 반영되지 않는다.
