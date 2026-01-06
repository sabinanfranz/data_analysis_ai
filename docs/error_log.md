---
title: Error Log & Mitigation Notes
last_synced: 2026-01-06
sync_source:
  - salesmap_first_page_snapshot.py
  - logs/run_history.jsonl
  - docs/snapshot_pipeline.md
  - docs/llm_context/05_SNAPSHOT_PIPELINE_CONTRACT.md
---

## Purpose
- Salesmap 스냅샷 실행 중 재현된 오류 패턴과 코드 기반 대응/복구 방법을 기록한다.

## Behavioral Contract
- 스냅샷 교체 로직은 `replace_file_with_retry`가 최대 5회 `os.replace`를 시도하고, 모두 실패하면 `<dest_stem>_<run_tag>.db`로 rename/copy해 보존한다. psutil이 있을 때 잠금 프로세스를 로그에 남긴다.
- 체크포인트 저장은 rename 실패 시 최대 3회 재시도 후 tmp→본 파일 복사로 폴백한다(`CheckpointManager.save_table`).
- 실행 결과는 `logs/run_history.jsonl`에 run_tag/final_db_path/backup_path/테이블 row·col/에러 수를 append하고, DB `manifest`/`run_info` 테이블에도 기록한다.

## Invariants (Must Not Break)
- 잠금 발생 시 rename/copy 폴백 경로가 로그와 run_history에 남아야 하며, 원본 DB는 덮어쓰지 않는다(`replace_file_with_retry`).
- 체크포인트 rename 실패 시에도 `.json` 본 파일이 남거나 `.tmp`가 복사되어 resume가 가능해야 한다.
- run_history에는 `final_db_path`와 오류 count가 항상 포함되어야 한다(복구 추적 근거).

## Coupling Map
- 오류 핸들링 코드: `salesmap_first_page_snapshot.py`(`replace_file_with_retry`, `CheckpointManager.save_table`).
- 진단 근거: `logs/run_history.jsonl`, `manifest`/`run_info` 테이블.
- 참고 문서: `docs/snapshot_pipeline.md`가 정상 흐름과 옵션을 설명한다.

## Edge Cases & Failure Modes
- **DB 교체 실패(WinError 32)**: temp DB(`salesmap_latest.db.tmp`)가 잠금으로 교체되지 않으면 폴백 DB(`salesmap_latest_<run_tag>.db`)에 저장된다. 해결: 잠금 프로세스 종료 후 폴백 DB를 `salesmap_latest.db`로 교체 또는 스냅샷 재실행.
- **체크포인트 rename 권한 거부(WinError 5)**: `.json.tmp`를 `.json`으로 rename하지 못해 크래시. 현재는 최대 3회 재시도 후 tmp→복사 폴백. 수동 복구는 `.tmp`를 `.json`으로 복사 후 `--resume --resume-run-tag <tag>`.
- **max_retries_exceeded(429/네트워크)**: SalesmapClient 재시도 후에도 실패하면 manifest에 오류가 남고 실행이 중단된다. 로그와 run_history에서 에러를 확인해야 한다.

## Verification
- 잠금 상황을 만들어 `replace_file_with_retry`가 폴백 경로를 생성하고 run_history에 기록되는지 확인한다.
- 체크포인트 저장 실패 시 `.json.tmp`가 복사되어 `--resume --resume-run-tag`로 재개 가능한지 검증한다.
- run_history.jsonl와 DB `manifest`/`run_info`가 항상 최신 run_tag와 에러 수를 포함하는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 교체/체크포인트 폴백 로직이 `salesmap_first_page_snapshot.py`에만 존재하며 다른 스크립트와 공유되지 않는다.
- 잠금 원인 파악은 psutil 유무에 따라 로그에만 의존하므로, 추가 메트릭 없이 재현/분석이 어렵다.
- run_history.jsonl와 manifest/run_info가 분리되어 있어 장애 조사 시 두 위치를 모두 확인해야 한다.
