---
title: User Guide (PowerShell 한 줄 실행)
last_synced: 2025-12-24
sync_source:
  - org_tables_v2.html
  - dashboard/server/main.py
  - salesmap_first_page_snapshot.py
  - docs/org_tables_v2.md
---

# User Guide (PowerShell 한 줄 실행)

## org_tables_v2 실행/재실행
1) 백엔드 기동(필수, FastAPI):  
```powershell
.\.venv\Scripts\python.exe -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port 8000 --reload
```
2) 프런트 열기(정적 서버):  
```powershell
python -m http.server 8001; Start-Process "http://localhost:8001/org_tables_v2.html"
```
   - 파일만 열 경우: `Start-Process .\org_tables_v2.html` (API는 기본 `http://localhost:8000/api` 사용).
3) 필요 시 venv 생성/의존성 설치:  
```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
```
4) 조직 드롭다운/조회 동작 안내:
   - 회사 목록은 People 또는 Deal이 1건 이상 연결된 조직만 표시되며, 2025년 Won 금액 합계 내림차순으로 정렬된다(동률 시 이름 순).
   - 페이지 진입/선택 초기화 후에는 자동으로 회사를 선택하지 않는다. 반드시 드롭다운에서 회사를 선택해야 People/Deal/JSON이 로드된다.
   - 규모 필터에서 결과가 0건이고 검색어가 비어 있으면 자동으로 `전체`로 전환해 재조회한다.
   - 회사 선택 후 `StatePath 보기` 버튼으로 2024/2025 상태·이벤트·추천을 모달로 확인할 수 있다(금액은 억 단위 표시).
   - 사이드바의 `StatePath 24→25` 메뉴에서는 규모 탭/검색/정렬 → 패턴 대시보드(전이 매트릭스/4셀 이벤트/rail 변화) → 테이블/페이지네이션/드로어/용어 안내(ⓘ/툴팁/모달)까지 제공된다. 금액은 모두 억 단위이며 캐시는 무효화되지 않는다.

## Salesmap 스냅샷(DB 생성)
- 사전 준비: PowerShell에서 환경 변수 `SALESMAP_TOKEN`을 설정.
- 실행(한 줄):
```powershell
$env:SALESMAP_TOKEN="<세일즈맵_API_토큰>"; python .\salesmap_first_page_snapshot.py --db-path .\salesmap_latest.db --log-dir .\logs --checkpoint-dir .\logs\checkpoints --backup-dir .\backups --keep-backups 30
```
- 체크포인트는 `logs/checkpoints`에 저장되며, 파일 교체 실패 시 자동으로 tmp→본 파일 복사로 폴백합니다. 중단 후 재개하려면 같은 옵션에 `--resume`을 추가합니다.

## 웹폼 제출 내역만 수집
- 기존 스냅샷 DB에서 웹폼 제출 내역만 별도로 적재하려면:
```powershell
$env:SALESMAP_TOKEN="<세일즈맵_API_토큰>"; python .\salesmap_first_page_snapshot.py --webform-only --db-path .\salesmap_latest.db --log-dir .\logs
```

## Verification
- PowerShell 한 줄 명령으로 uvicorn/정적 서버가 기동되고 `http://localhost:8001/org_tables_v2.html`에서 API 호출이 성공하는지 확인한다.
- 사이드바에 교육1팀 딜체크 메뉴가 4번째로 노출되고 `/api/deal-check/edu1` 호출이 성공하는지 확인한다.
- 스냅샷 명령 실행 시 logs/run_history.jsonl에 기록이 남고 replace_file_with_retry의 폴백 로그가 출력되는지 확인한다.
- `--webform-only` 실행 후 `webform_history` 테이블 row 수가 증가하는지 sqlite로 확인한다.
