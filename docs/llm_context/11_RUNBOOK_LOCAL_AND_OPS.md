---
title: Runbook: 로컬 실행 & 운영(스냅샷/복구)
last_synced: 2025-12-24
sync_source:
  - salesmap_first_page_snapshot.py
  - org_tables_v2.html
  - docs/user_guide.md
  - docs/snapshot_pipeline.md
  - logs/run_history.jsonl
---

# Runbook: 로컬 실행 & 운영(스냅샷/복구)

## 1) 로컬 실행 (백엔드/프런트)
- 백엔드(FastAPI):  
  ```powershell
  .\.venv\Scripts\python.exe -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload
  ```
- 프런트(정적 서버) 또는 파일 직접 열기:  
  ```powershell
  python -m http.server 8001
  Start-Process "http://localhost:8001/org_tables_v2.html"
  ```  
  또는 `Start-Process .\org_tables_v2.html` (API 기본 `http://localhost:8000/api`).
  - StatePath 확인: 조직 선택 후 `StatePath 보기` 버튼으로 `/api/orgs/{id}/statepath` 응답을 모달로 확인(억 단위 금액 그대로 표시).
  - 교육1팀 딜체크 확인: 사이드바 4번째 메뉴에서 `/api/deal-check/edu1` 데이터를 로드하고 리텐션/신규 테이블이 분리되는지 확인.

## 2) 스냅샷 실행 (전체 수집)
- 필수: `SALESMAP_TOKEN` 설정.
- 기본 예시:  
  ```powershell
  $env:SALESMAP_TOKEN="<토큰>"; python .\salesmap_first_page_snapshot.py --db-path .\salesmap_latest.db --log-dir .\logs --checkpoint-dir .\logs\checkpoints --backup-dir .\backups --keep-backups 30
  ```
- 옵션: `--resume`(최근 체크포인트 재개), `--resume-run-tag`(특정 run_tag 재개), `--checkpoint-interval`(기본 50), `--webform-only`(아래 3).

## 3) 웹폼만 실행
- 기존 DB에서 웹폼 제출 내역만 재수집/적재:  
  ```powershell
  $env:SALESMAP_TOKEN="<토큰>"; python .\salesmap_first_page_snapshot.py --webform-only --db-path .\salesmap_latest.db --log-dir .\logs
  ```

## 4) 장애 복구 시나리오
- **DB 잠금으로 교체 실패**  
  - 흔한 원인: Windows에서 DB를 연 프로그램(브라우저/SQLite 뷰어 등) 잠금.  
  - 조치: 잠금 프로세스 종료 → `backups/`에 남은 이전 DB 확인 → 필요 시 `logs/checkpoints/`의 체크포인트 DB로 수동 교체.  
  - `replace_file_with_retry`가 최대 5회 재시도 후 폴백하므로 로그(`logs/…`)에서 교체 실패 여부 확인.
- **체크포인트 rename 권한 거부**  
  - 증상: `.tmp` 파일만 남고 최종 `.json`/DB로 rename 실패.  
  - 조치: `.tmp`를 수동으로 `.json`(또는 DB) 이름으로 복사/덮어쓰기 후 `--resume`으로 재개.
- **실패 시 데이터 잔존 위치**  
  - `backups/` : 마지막 성공본.  
  - `logs/checkpoints/` : 중간 진행분(재개 가능).  
  - `logs/` : manifest/run_info, 에러 로그.

## 5) 실행 전 점검 체크리스트
- DB/로그/백업/체크포인트 경로에 쓰기 권한 확인.
- DB를 여는 다른 프로그램(뷰어, 브라우저 플러그인 등) 닫기 → 잠금 방지.
- 디스크 여유 공간 확인(체크포인트/백업 유지).
- 네트워크/토큰 준비: `SALESMAP_TOKEN` 설정, API Base 기본 `https://salesmap.kr/api/v2`(변경 시 `SALESMAP_API_BASE`).

## Verification
- FastAPI/프런트 기동 후 사이드바 메뉴(특히 교육1팀 딜체크)가 정상 표시되고 API 호출이 성공하는지 확인한다.
- 스냅샷 실행 시 logs/run_history.jsonl에 final_db_path와 run_info/manifest가 기록되는지 확인한다.
- DB 잠금/체크포인트 rename 실패 시 로그에 retry/폴백 메시지가 남고 tmp→복사로 해결 가능한지 테스트한다.
- `--resume` 또는 `--resume-run-tag`로 중단 지점에서 재개되는지 체크포인트를 사용해 확인한다.
