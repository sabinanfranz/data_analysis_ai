---
title: Salesmap Snapshot Pipeline
last_synced: 2025-12-24
sync_source:
  - salesmap_first_page_snapshot.py
  - logs/run_history.jsonl
  - docs/error_log.md
  - docs/llm_context/05_SNAPSHOT_PIPELINE_CONTRACT.md
---

# Salesmap Snapshot Pipeline

이 프로젝트는 Salesmap API 데이터를 SQLite로 스냅샷하며, 대량 데이터와 네트워크/잠금 이슈에 대비한 복구·재개 기능을 포함합니다.

## 주요 동작 흐름 (`salesmap_first_page_snapshot.py`)
- **토큰/설정**: `SALESMAP_TOKEN` 필요. CLI 옵션으로 DB 경로, 로그 경로, 체크포인트 경로, 백업 보관 개수, 재개 여부를 제어합니다.
- **로깅/히스토리**: 콘솔+파일 로깅(`logs/`). 실행 요약은 `logs/run_history.jsonl`에 JSONL로 append되며, `final_db_path`, 에러 수, 테이블별 row/col를 기록합니다.
- **백업**: 기존 DB가 있으면 `backups/`에 압축 백업 생성(옵션으로 비활성화 가능).
- **페이지 수집**: 엔드포인트별 커서 페이지를 순회하며 `TableWriter`가 바로 SQLite에 append합니다. 스키마는 데이터에 맞춰 자동 확장됩니다.
- **동적 백오프/재시도**: 호출 최소 간격 유지. 429는 `Retry-After` 우선, 없으면 지수 백오프. 5xx/네트워크 예외도 지수 백오프 후 재시도(최대 `MAX_RETRIES`).
- **체크포인트/재개**: N페이지마다 커서·페이지·열 정보를 `logs/checkpoints/checkpoint_<run_tag>.json`에 저장. `--resume`/`--resume-run-tag`로 직전 커서부터 이어서 동일 temp DB에 추가합니다.
- **루프 방지**: 커서 반복 감지 시 중단하고 에러 기록.
- **작성 완료 후 교체**: temp DB(`salesmap_latest.db.tmp`)를 최종 DB로 교체. 잠금 시 리트라이 후, 여전히 실패하면 `salesmap_latest_<run_tag>.db`로 rename/copy하여 데이터는 보존합니다(로그에 경고).
- **SQLite finalize**: 완료 직전 WAL 체크포인트/optimize/commit/close + GC + 짧은 대기 후 교체 시도(윈도우 핸들 해제 지연 대비). 교체 실패 시 psutil이 있으면 잠금 프로세스를 로그로 노출.
- **체크포인트 저장 폴백**: 체크포인트 파일 rename 실패(WinError 5 등) 시 3회 재시도 후 tmp→본 파일 복사로 저장, 실패 시 예외와 로그를 남깁니다. 필요하면 `.tmp`를 수동으로 `.json`에 복사해 재개 가능합니다.
- **후처리: 웹폼 제출 내역 수집**: 스냅샷이 성공적으로 완료되면 `deal.peopleId`에 연결된 People의 `제출된 웹폼 목록`에서 webform id를 모으고, 각 id에 대해 `/v2/webForm/<id>/submit` API를 페이지네이션(cursor)로 호출해 `webform_history` 테이블을 추가로 업데이트합니다. 컬럼이 없거나 id가 없을 경우 건너뜁니다.
- **웹폼만 단독 실행**: `--webform-only` 옵션으로 기존 DB(`--db-path`)에 대해 웹폼 제출 내역만 수집/적재할 수 있습니다. 예) `python salesmap_first_page_snapshot.py --webform-only --db-path salesmap_latest.db`.
- **허용 ID 필터링**: webform 제출은 `deal.peopleId` 기반 허용 People ID 집합에만 적재하며, peopleId가 없거나 허용 목록 외인 건은 dropped_missing/dropped_not_allowed로 집계 후 건너뛴다.

## 주요 옵션
- `--db-path`: 최종 SQLite 경로(기본 `salesmap_latest.db`).
- `--log-dir`: 로그/히스토리 경로(기본 `logs/`).
- `--checkpoint-dir`: 체크포인트 경로(기본 `logs/checkpoints`).
- `--checkpoint-interval`: 체크포인트 저장 페이지 주기(기본 50).
- `--resume`, `--resume-run-tag`: 체크포인트 기반 재개.
- `--backup-dir`, `--keep-backups`, `--no-backup`: 백업 제어.

## 정상/장애 시나리오
- **정상 완료**: `run_history.jsonl`에 성공 기록, `final_db_path`가 최종 DB. `manifest`, `run_info` 테이블이 SQLite에 존재.
- **네트워크/429/5xx**: 백오프 후 재시도. `max_retries_exceeded` 발생 시 해당 페이지에서 중단하고 에러가 manifest/히스토리에 기록.
- **커서 루프**: 반복 커서 감지 시 중단, 에러로 기록.
- **DB 잠금**: `salesmap_latest.db`가 잠겨 있으면 교체 실패 → rename/copy 폴백 파일이 생성되고 경고 로그 남김. 잠금 해제 후 폴백 파일을 수동 교체 가능.
- **체크포인트 잠금/권한 문제**: 체크포인트 `.json.tmp` rename 실패 시 자동 복사 폴백. 그래도 막히면 tmp를 수동 복사(`Copy-Item checkpoint_xxx.json.tmp checkpoint_xxx.json -Force`) 후 `--resume --resume-run-tag xxx`로 재개.

## 테스트
- `python3 -m unittest discover -s tests` 로 유닛 테스트 실행. TableWriter, 체크포인트, 백오프/폴백 로직을 커버합니다(로컬에 pandas 없을 때를 위한 스텁 포함).

## Verification
- 스냅샷 실행 시 logs/run_history.jsonl에 final_db_path, 에러 수, 테이블별 row/col이 기록되는지 확인한다.
- 교체 실패 시 replace_file_with_retry의 retry/rename/copy 폴백 로그가 남고 백업/폴백 DB가 생성되는지 확인한다.
- 체크포인트 `.json`이 생성되고 rename 실패 시 tmp→복사가 수행되는지 확인한다.
- `--webform-only` 실행 시 기존 DB에 webform_history가 업데이트되고 dropped_missing/dropped_not_allowed 카운트가 로그에 표시되는지 확인한다.
