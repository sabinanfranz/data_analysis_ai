---
title: 스냅샷 파이프라인 계약
last_synced: 2026-12-11
sync_source:
  - salesmap_first_page_snapshot.py
  - logs/run_history.jsonl
absorbed_from:
  - snapshot_pipeline.md
  - error_log.md
---

## Purpose
- `salesmap_first_page_snapshot.py` 스냅샷 파이프라인의 실행 흐름, 체크포인트/백업/웹폼 후처리 계약을 요약한다.

## Behavioral Contract
- CLI 옵션: `--db-path`(기본 `salesmap_latest.db`), `--log-dir`(`logs`), `--checkpoint-dir`(`logs/checkpoints`), `--backup-dir`(`backups`), `--keep-backups`(기본 30), `--checkpoint-interval`(기본 50), `--resume`/`--resume-run-tag`, `--webform-only`, `--base-url`(기본 `https://salesmap.kr/api/v2`), `--token`(미지정 시 env `SALESMAP_TOKEN` 필수).
- 실행 흐름:
  1) 로깅 초기화(`setup_logging`).
  2) 기존 DB 백업(`maybe_backup_existing_db`) 후 temp DB 준비. resume 시 checkpoint에 기록된 temp 경로 사용.
  3) 페이지네이션 엔드포인트(`/organization`, `/people`, `/deal`, `/lead`, `/memo`)를 `capture_paginated`로 수집하며 N페이지마다 체크포인트 저장; `/user`, `/team`은 단건.
  4) manifest/run_info를 temp DB에 기록 후 WAL 체크포인트/optimize(`finalize_sqlite_connection`).
  5) tmp→최종 DB 교체(`replace_file_with_retry` 최대 5회, 실패 시 `<stem>_<run_tag>.db` 폴백).
  6) webform_history 후처리(`update_webform_history`)로 허용 People ID만 `/v2/webForm/<id>/submit`에서 수집.
  7) 실행 결과를 `logs/run_history.jsonl`에 append.
- 재시도/백오프: `SalesmapClient`가 요청 전 최소 0.12s 간격을 보장, 429는 `Retry-After` 또는 지수(10s) 백오프, 5xx/네트워크 오류도 지수 백오프 후 최대 3회 시도.
### (흡수) 상세 실행/옵션/후처리
- 토큰/경로: `SALESMAP_TOKEN` 미설정 시 즉시 종료. 기본 경로는 DB=`salesmap_latest.db`, 로그=`logs`, 체크포인트=`logs/checkpoints`, 백업=`backups`, `DEFAULT_BASE_URL=https://salesmap.kr/api/v2`. `--keep-backups` 기본 30, temp DB는 `.tmp` 확장자를 사용한다.
- 체크포인트: `CheckpointManager.save_table`이 `<checkpoint_dir>/checkpoint_<run_tag>.json.tmp`에 저장 후 rename, 실패 시 최대 3회 재시도하고 copy 폴백을 남긴다(resume 시 동일 경로 사용).
- 교체/히스토리: `replace_file_with_retry`가 최대 5회 `os.replace`를 시도하고, 실패 시 `<dest_stem>_<run_tag>.db` rename/copy 폴백을 기록한다. 성공/실패 여부, 백업 경로, manifest row/col을 `logs/run_history.jsonl`과 DB `manifest/run_info`에 기록한다.
- 웹폼 후처리: `update_webform_history`가 peopleId/webFormId가 있는 행만 `/v2/webForm/<id>/submit`로 호출해 `webform_history` 테이블을 채우며, 허용 People ID 밖은 dropped_*로 기록한다. `--webform-only`는 스냅샷을 건너뛰고 후처리만 수행한다.

## Invariants (Must Not Break)
- `SALESMAP_TOKEN` 없으면 즉시 종료; webform-only 실행도 토큰 필수.
- 체크포인트는 `.json.tmp`에 저장 후 rename, 실패 시 최대 3회 재시도 후 tmp→복사 폴백을 수행한다.
- DB 교체는 최대 5회 `os.replace`; 모두 실패하면 rename/copy 폴백 파일 경로를 로그/run_history에 남긴다.
- run_history.jsonl에는 `run_tag`, `final_db_path`, `backup_path`, 테이블별 row/col, 오류 개수가 항상 기록된다.
- webform_history 적재는 peopleId/webFormId가 비어 있으면 건너뛰며 dropped_* 카운트를 로그에 남긴다.
### (흡수) 경로/간격/캐시 불변조건
- 기본 경로 상수(DB/로그/체크포인트/백업)와 `MIN_INTERVAL=0.12`, `MAX_RETRIES=3`, `BACKOFF_429=10.0` 값은 실행마다 동일해야 한다.
- 백업은 기존 DB가 있을 때만 생성되며 `--no-backup`이 아닌 한 gzip으로 압축 후 `--keep-backups` 개수만 남긴다.

## Coupling Map
- 스크립트: `salesmap_first_page_snapshot.py`(SalesmapClient, TableWriter, CheckpointManager, replace_file_with_retry, update_webform_history).
- 로그/산출물: `logs/`(run_history.jsonl, 개별 로그), `logs/checkpoints/`, `backups/`, 최종 DB.
- 소비: FastAPI/프런트(`dashboard/server/*`, `org_tables_v2.html`)가 생성된 DB를 직접 읽는다.
### (흡수) 장애 기록 근거
- 장애 진단은 `logs/run_history.jsonl`, `manifest`/`run_info` 테이블과 로그에 남는 잠금/폴백/재시도 메시지를 함께 확인한다.

## Edge Cases & Failure Modes
- DB 교체 잠금(WinError 32 등) → 폴백 DB가 생성되고 원본이 유지된다; 잠금 해제 후 수동 교체 필요.
- 체크포인트 rename 권한 오류(WinError 5 등) → `.tmp` 복사 폴백으로 저장되며 resume 가능.
- 429/5xx 반복 → `max_retries_exceeded`로 중단되고 manifest/errors에 기록된다.
- resume 시 체크포인트 row_count와 실제 테이블 row_count가 다르면 경고만 출력하고 계속 진행한다.
### (흡수) 최근 장애 패턴
- `replace_file_with_retry`가 잠금으로 5회 연속 실패하면 `<dest_stem>_<run_tag>.db` 폴백을 남기고 run_history에 경로를 기록한다(psutil이 있으면 잠금 프로세스 PID/이름을 경고에 남김).
- `CheckpointManager.save_table` rename 실패가 반복되면 `.json.tmp`를 `.json`으로 복사해 저장하며, WinError 5(권한 거부)에서도 복사 폴백으로 이어간다.
- 429/네트워크 오류 재시도가 모두 실패하면 manifest/errors와 run_history.jsonl에 오류 개수가 기록되고 실행이 중단된다.

## Verification
- `$env:SALESMAP_TOKEN="..."; python salesmap_first_page_snapshot.py --db-path salesmap_latest.db --log-dir logs` 실행 후 run_history.jsonl에 final_db_path/backup_path가 기록되는지 확인한다.
- temp DB 교체 실패를 유발해 폴백 파일이 생성되고 로그에 경고가 남는지 확인한다.
- 체크포인트 `.json`이 주기적으로 생성되고 rename 실패 시 `.tmp` 복사본이 남는지, `--resume --resume-run-tag`로 재개 가능한지 확인한다.
- webform-only 실행이 기존 테이블을 변경하지 않고 webform_history만 갱신하는지 spot-check한다.
- WinError 32/5 상황을 시뮬레이션해 `replace_file_with_retry`/`CheckpointManager.save_table`가 폴백 경로와 경고를 남기는지, run_history.jsonl에 오류/경로가 기록되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 백업/로그/체크포인트 경로와 파일명이 코드 상수로 중복되어 환경별 설정 분리가 어렵다.
- webform 후처리가 스냅샷 완료 후에만 실행되고 실패 시 경고만 남겨 최신성이 보장되지 않는다.
- replace_file_with_retry/CheckpointManager의 잠금 대응 로직이 다른 파이프라인에 공유되지 않는다.
### (흡수) 추가 리팩터링 고려
- 교체/체크포인트 폴백 로직이 Windows 파일 잠금 패턴에 맞춰져 있어 다른 OS/스크립트로 확장할 수 있도록 공통 모듈화가 필요하다.
- run_history.jsonl와 manifest/run_info를 동시에 봐야 장애 원인을 파악할 수 있으므로 단일 진단 뷰나 알림 연동이 필요하다.
