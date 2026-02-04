---
title: 스냅샷 파이프라인 계약
last_synced: 2026-02-04
sync_source:
  - salesmap_first_page_snapshot.py
  - salesmap_latest.db
  - logs/run_history.jsonl
  - .github/workflows/salesmap_db_daily.yml
---

## Purpose
- Salesmap API를 전량 수집해 SQLite 스냅샷(`salesmap_latest.db`)을 생성/교체하는 `salesmap_first_page_snapshot.py`의 실제 동작·옵션·산출물 계약을 명시한다.

## Behavioral Contract
- 필수 토큰: CLI `--token` 미지정 시 `SALESMAP_TOKEN`(env 또는 streamlit secrets) 없으면 즉시 종료.
- 기본 옵션/경로 (파라미터가 없을 때):
  - `--base-url` = `https://salesmap.kr/api/v2` (env `SALESMAP_API_BASE`로 override 가능)
  - `--db-path` = `salesmap_latest.db`
  - `--backup-dir` = `backups`, `--keep-backups` = 30, `--no-backup`로 백업 비활성
  - `--log-dir` = `logs`, 로그 파일명 `salesmap_snapshot_<run_tag>.log`
  - `--checkpoint-dir` = `logs/checkpoints`, `--checkpoint-interval` = 50 페이지
  - 재개 옵션: `--resume`(가장 최근 체크포인트 자동 선택) 또는 `--resume-run-tag <tag>`
  - `--webform-only`: 스냅샷 크롤은 건너뛰고 webform_history만 업데이트
- 호출/적재 흐름(기본 run):
  1) 로깅 초기화 → run_tag 생성(UTC `YYYYMMDD_HHMMSS`).
  2) 기존 DB가 있고 `--no-backup`이 아니면 zip 백업 생성(`backups/salesmap_backup_<run_tag>.zip`) 후 `--keep-backups` 개수만 남기고 나머지 삭제.
  3) temp DB 경로 준비: 기본 `<db_path>.tmp`; resume 시 체크포인트의 `db_tmp_path` 재사용. 기존 tmp가 있으면 삭제 시도 후 필요 시 `<stem>_<run_tag>.tmp` 대체.
  4) CheckpointManager 로딩(파일 `checkpoint_<run_tag>.json`); resume 시 테이블별 cursor/page/columns/rows를 복원.
  5) 수집 대상
     - 페이지네이션: `/organization`→organization, `/people`→people, `/deal`→deal, `/lead`→lead, `/memo`→memo
     - 단건 리스트: `/user`→user, `/team`→team
     - 각 응답 리스트 키: `organizationList`, `peopleList`, `dealList`, `leadList`, `memoList`, `userList`, `teamList`
     - `TableWriter`가 발견한 새 컬럼을 즉시 `ALTER TABLE ... ADD COLUMN <TEXT>`로 append-only 추가하고, batch를 pandas로 append 저장
     - 페이지 N마다 체크포인트 저장; cursor 루프 감지 시 errors에 `cursor_loop` 기록 후 중단
  6) manifest/run_info 작성: temp DB에 `manifest(table, endpoint, row_count, column_count, errors)`와 `run_info(run_tag, captured_at_utc, base_url, endpoints, checkpoint_path, final_db_path)` 저장.
  7) SQLite finalize: commit → WAL checkpoint(TRUNCATE) → PRAGMA optimize → close → gc → 0.5s sleep.
  8) tmp→최종 DB 교체: `replace_file_with_retry`가 최대 5회 `os.replace`(0.5s 간격) 시도, 잠금 시 psutil로 잠금 프로세스 로깅. 모두 실패하면 `<dest_stem>_<run_tag>.db`로 rename/copy 폴백하고 경고 로그.
  9) webform_history 후처리: deal.peopleId 집합을 기반으로 people."제출된 웹폼 목록"에서 webform id를 수집해 `/webForm/{id}/submit`(cursor 지원) 호출, peopleId 불일치/누락은 dropped_*로 집계 후 로그. 테이블이 없으면 건너뛰고 로그.
  10) run_history.jsonl append: run_tag, captured_at_utc, final_db_path, log_path, backup_path, 테이블별 row/col, manifest errors 요약.
- 웹 요청 재시도/백오프: 최소 간격 0.12s; 429 시 Retry-After(있으면) 또는 10s*시도, 5xx/네트워크 오류는 동일 백오프, 최대 3회, MAX_BACKOFF=60s.

## Invariants (Must Not Break)
- 필수 env: `SALESMAP_TOKEN` (webform-only 포함).
- 스냅샷 테이블 세트는 `organization/people/deal/lead/memo/user/team` 이어야 하며 TEXT 컬럼 append-only.
- 체크포인트 파일: `<checkpoint_dir>/checkpoint_<run_tag>.json`에 page/cursor/rows/columns/완료 여부가 저장되어 resume 가능해야 한다.
- 교체 실패 시 최종 DB는 원본을 보존하고 폴백 DB 경로가 로그와 run_history에 남아야 한다.
- manifest/run_info/run_history는 항상 작성되어야 하며, 오류 발생 시 errors 필드에 누락 없이 기록된다.

## Coupling Map
- 생산: `salesmap_first_page_snapshot.py` (SalesmapClient, TableWriter, CheckpointManager, replace_file_with_retry, update_webform_history).
- 소비: `dashboard/server/database.py`(FastAPI 집계), `org_tables_v2.html`(프런트), CI 배포(`.github/workflows/salesmap_db_daily.yml`), 로컬 runbook(start.sh)이 최종 DB를 사용한다.
- 백업/로그 산출물: `backups/`, `logs/`, `logs/checkpoints/`, `run_history.jsonl`.

## Edge Cases & Failure Modes
- DB 파일 잠금(WinError 32 등): 5회 교체 실패 시 `<db_stem>_<run_tag>.db` 폴백을 남기고 경고 로그, 원본 보존.
- 체크포인트 rename 권한 오류(WinError 5 등): `.json.tmp`를 `.json`으로 복사하는 폴백을 수행하고 경고 로그.
- cursor 반복 감지: `cursor_loop` 오류를 manifest.errors에 기록하고 해당 엔드포인트 중단.
- webform_history: people set 비어 있으면 스킵, people 컬럼 미존재 시 로깅 후 스킵, peopleId 불일치/누락은 dropped_not_allowed/dropped_missing으로 합산.
- resume 시 checkpoint rows와 실제 테이블 row_count가 다르면 경고만 출력하고 계속 진행.

## Verification
- 환경 변수로 토큰 설정 후 전체 실행
  ```bash
  SALESMAP_TOKEN=*** python3 salesmap_first_page_snapshot.py \
    --db-path salesmap_latest.db \
    --log-dir logs --checkpoint-dir logs/checkpoints --backup-dir backups
  ```
  - 실행 후 `logs/run_history.jsonl` 마지막 행에 final_db_path/log_path/backup_path와 각 테이블 row/col이 기록되는지 확인
  - `sqlite3 salesmap_latest.db 'SELECT COUNT(*) FROM manifest;'`가 7(collect된 테이블 수)인지 확인
  - `ls backups/salesmap_backup_*.zip | tail -1`로 최신 백업 생성 여부 확인 (`--no-backup` 사용 시 생성되지 않아야 함)
- webform-only 모드
  ```bash
  SALESMAP_TOKEN=*** python3 salesmap_first_page_snapshot.py --webform-only --db-path salesmap_latest.db
  ```
  - `webform_history` row 수 증가, 다른 테이블 row/스키마 변화 없음 확인
- 교체 잠금 폴백 시나리오: snapshot 실행 중 대상 DB를 열어두고 실행 → logs에 폴백 경고 및 `_ <run_tag>.db` 파일 생성되는지 확인

## Refactor-Planning Notes (Facts Only)
- 백업/로그/체크포인트 경로 상수가 코드 곳곳에 중복 정의되어 환경 분리·설정 주입이 어렵다.
- webform 후처리가 best-effort로 실행되어 실패 시 재시도/알림이 없다.
- replace_file_with_retry/CheckpointManager의 잠금 대응 로직을 공통 유틸로 분리하면 다른 파이프라인에서도 재사용 가능하다.
