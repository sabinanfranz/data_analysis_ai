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
