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
