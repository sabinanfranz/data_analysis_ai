---
title: Error Log & Mitigation Notes
last_synced: 2025-12-24
sync_source:
  - salesmap_first_page_snapshot.py
  - logs/run_history.jsonl
  - docs/snapshot_pipeline.md
  - docs/llm_context/05_SNAPSHOT_PIPELINE_CONTRACT.md
---

# Error Log & Mitigation Notes

최근 스냅샷 실행 중 발생한 주요 오류와 대응 방법 정리.

## 2025-12-07 – DB 잠금으로 교체 실패
- **증상**: 수집 완료 후 `os.replace(salesmap_latest.db.tmp -> salesmap_latest.db)`가 `WinError 32`로 5회 실패. 잠금 상태가 강해 폴백 rename까지 막힘 (`salesmap_latest_<run_tag>.db`로 이동 실패).
- **원인 추정**: `salesmap_latest.db`가 외부 프로세스(뷰어, 백업, AV 등)에 의해 잠겨 있음.
- **영향**: 새 데이터는 temp 파일(`salesmap_latest.db.tmp`)에 존재. 기존 DB는 잠금 상태로 유지, run_info/history 기록은 마무리되지 못함.
- **조치**:
  - `replace_file_with_retry` 개선: 교체 실패 시 rename 시도, rename도 실패하면 `shutil.copyfile`로 폴백 DB 생성.
  - 교체 실패 시 psutil로 잠금 프로세스 로깅(가능한 경우).
  - 로그/히스토리에 `final_db_path` 기록, 폴백 경로 확인 용이.
  - 실행 전 DB 파일을 사용하는 앱(Excel/DB 뷰어/백업/AV)을 닫도록 안내.
- **회복 절차**:
  1. `salesmap_latest.db` 잠금을 푼다(관련 앱 종료).
  2. temp 또는 폴백 DB를 `salesmap_latest.db`로 수동 교체하거나, 잠금 해제 후 스크립트를 재실행(`--resume` 가능).
  3. 성공 후 `manifest`/`run_info` 테이블과 `logs/run_history.jsonl`에서 상태 확인.

## 일반적인 오류 유형
- **429 Too Many Requests**: `Retry-After` 기반 백오프, 지수 재시도 적용됨. 지속 시 interval 증가 후 재실행.
- **5xx/네트워크 오류**: 지수 백오프 후 재시도, `max_retries_exceeded` 시 해당 페이지 중단 및 오류 기록(체크포인트/manifest에 남음).
- **커서 루프**: 같은 cursor 반복 시 탐지 후 중단, 오류 기록.
- **윈도우 파일 핸들 지연 해제**: 종료 후 핸들 해제 지연을 대비해 finalize 단계에서 commit/close, GC, 약간의 sleep 추가.

## 재발 방지 체크리스트
- 실행 전 DB 파일을 여는 모든 프로세스 종료.
- 필요 시 `--checkpoint-interval`을 줄여 더 자주 저장.
- 장시간 실행 시 로그/백업 디스크 공간 확보.
- 실패 후 재실행 시 `--resume` 또는 특정 `--resume-run-tag` 사용.

## 2025-12-09 – 체크포인트 rename 권한 거부(WinError 5)
- **증상**: 체크포인트 저장 시 `checkpoint_<run_tag>.json.tmp -> .json` rename 단계에서 `PermissionError [WinError 5]`로 크래시.
- **원인 추정**: Windows에서 `.json` 또는 `.tmp`에 대한 잠금/권한 충돌(편집기/탐색기/백업 도구 등).
- **영향**: 데이터는 temp DB(`salesmap_latest.db.tmp`)에 쓰였으나, 최신 체크포인트가 `.tmp`에만 존재해 재개가 번거로움. run_history/manifest 미완료.
- **조치**:
  - `CheckpointManager.save_table`에 rename 3회 재시도 후 tmp→본 파일 복사 폴백 추가(로그 경고).
  - 수동 복구 절차 문서화: `.tmp`를 `.json`으로 복사(`Copy-Item checkpoint_xxx.json.tmp checkpoint_xxx.json -Force`) 후 `--resume --resume-run-tag xxx`로 재개.
- **회복 절차**:
  1. 관련 파일을 열어둔 앱/탐색기 탭을 닫아 잠금 해제.
  2. `.tmp`를 `.json`으로 수동 복사(필요 시 `.bak` 백업 후 덮어쓰기).
  3. `--resume --resume-run-tag <run_tag>`로 재실행하여 manifest/run_history까지 마무리.
  4. 완료 후 `logs/run_history.jsonl`의 `final_db_path`와 DB의 `run_info`/`manifest` 테이블을 확인.

## Verification
- `logs/run_history.jsonl`에 DB 교체 실패 시 `final_db_path`가 폴백 경로로 기록되는지 확인한다.
- `salesmap_first_page_snapshot.py` 로그에서 replace_file_with_retry의 retry/rename/copy 폴백 메시지가 출력되는지 확인한다.
- 체크포인트 rename 실패 상황에서 `.json.tmp`를 수동 복사 후 `--resume --resume-run-tag`로 정상 재개되는지 테스트한다.
- 재개/복구 후 `run_info`/`manifest` 테이블이 채워지고 temp DB가 남아 있지 않은지 확인한다.
