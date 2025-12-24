---
title: 스냅샷 파이프라인 운영 계약
last_synced: 2025-12-24
sync_source:
  - salesmap_first_page_snapshot.py
  - docs/snapshot_pipeline.md
  - logs/run_history.jsonl
  - docs/error_log.md
---

# 스냅샷 파이프라인 운영 계약

## 1) 목적 & 입력
- 목적: Salesmap API 데이터를 받아 `salesmap_latest.db`(SQLite) 스냅샷을 생성/교체하고, 웹폼 제출 내역을 `webform_history`에 적재한다.
- 입력/옵션:
  - 환경변수: `SALESMAP_API_BASE`(기본 `https://salesmap.kr/api/v2`), `SALESMAP_TOKEN`(필수).
  - CLI: `--db-path`(기본 `salesmap_latest.db`), `--backup-dir`(기본 `backups`), `--log-dir`(기본 `logs`), `--checkpoint-dir`(기본 `logs/checkpoints`), `--checkpoint-interval`(기본 50), `--keep-backups`(기본 30), `--resume`, `--resume-run-tag`, `--webform-only` 등.

## 2) 실행 단계
1. **백업 준비**: 기존 DB를 백업 디렉터리로 보존(keep N=30 기본).
2. **수집**: Salesmap API 호출로 organization/people/deal/lead/… 테이블 데이터를 수집.
3. **체크포인트**: `checkpoint_dir`에 주기(`checkpoint_interval`)마다 중간 DB/메타를 저장.
4. **finalize**: manifest(테이블 행/컬럼 카운트, 에러)와 run_info(실행 메타) 작성.
5. **파일 교체**: 임시 DB → `replace_file_with_retry`로 최종 DB 교체(잠금 시 재시도 후 rename/copy 폴백까지 수행).
6. **webform_history 후처리**: 웹폼 제출 내역을 peopleId/webFormId 기준으로 적재(페이지네이션 처리).

## 3) 재시도/백오프 정책
- 요청 기본: `MAX_RETRIES=3`, `MIN_INTERVAL=0.12s`(호출 간 최소 간격).
- 429 대응: `BACKOFF_429=10s`를 시도 횟수에 곱해 `MAX_BACKOFF=60s`까지 지수 백오프. `Retry-After` 헤더가 있으면 우선 적용.
- 네트워크/RequestException: 같은 백오프 로직으로 재시도. 5xx는 코드에 명시적 처리 없음 → 실패 시 예외(필요 시 TODO).

## 4) 체크포인트/재개 계약
- 옵션: `--resume`(최신 체크포인트에서 재개), `--resume-run-tag`(특정 run_tag 체크포인트에서 재개).
- 체크포인트 내용: 중간 DB 파일 + 테이블별 진행 상태를 `checkpoint_dir`에 저장.
- 재개 시 마지막 체크포인트를 불러와 이어서 수집 후 finalize/교체를 진행한다.
- 포맷/경로: `logs/checkpoints/<run_tag>/...` (rename 실패 시 tmp→본 파일 복사 폴백이 자동으로 적용됨).

## 5) 파일 교체 계약
- 함수: `replace_file_with_retry(src, dest, attempts=5, delay=0.5)`.
- 동작: 임시 파일을 최종 DB 경로로 이동. 잠금/권한 이슈가 있으면 최대 5회 재시도 → rename 시도 → 그래도 안 되면 `shutil.copyfile` 폴백(로그에 경고).
- 백업: 교체 전 기존 DB는 `--backup-dir` 아래에 보존(최근 N개 유지).

## 6) webform_history 후처리 계약
- 대상: 웹폼 제출 이벤트. `peopleId/webFormId/organizationId/dealId/leadId/createdAt/contents`를 저장.
- 허용 ID: peopleId 기준으로 매핑하며, 빈 값은 dropped_missing, 허용 목록 외는 dropped_not_allowed로 건너뛴다(로그에 카운트).
- 페이지네이션: Salesmap API 페이지 단위로 모든 제출을 순회(코드에서 반복 호출). 실패 시 재시도 로직 공유.

## 7) 실패 시 데이터 잔존 체크리스트
- 백업: `--backup-dir` 내 이전 DB가 남아 있는지 확인.
- 체크포인트: `logs/checkpoints/`에 중간 DB/메타가 있는지 확인(재개 가능).
- 임시 파일: 교체 직전 tmp/중간 DB가 `logs` 또는 작업 디렉터리에 남았는지 확인.
- manifest/run_info: 마지막 실행 메타가 생성됐는지 확인(없으면 finalize 이전에 실패한 것).
- 웹폼: webform_history가 비어 있으면 후처리 실패/미수행 가능성. 필요한 경우 `--webform-only`로 재수집.

## Verification
- `salesmap_first_page_snapshot.py` 실행 로그에 backup/replace_file_with_retry/rename→copy 폴백 메시지가 출력되는지 확인한다.
- 체크포인트가 `logs/checkpoints/<run_tag>/`에 저장되고 rename 실패 시에도 `.json`이 생성되는지 확인한다.
- webform_history 적재 시 dropped_missing/dropped_not_allowed 카운트가 로그에 기록되는지 확인한다.
- 실패 후 `--resume --resume-run-tag <tag>`로 재개할 때 checkpoint를 불러와 이어서 실행되는지 확인한다.
