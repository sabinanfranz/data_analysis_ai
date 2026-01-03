---
title: CI/CD & Railway 배포 계약 (GitHub Actions, start.sh)
last_synced: 2025-12-26
sync_source:
  - .github/workflows/salesmap_db_daily.yml
  - start.sh
  - salesmap_first_page_snapshot.py
  - requirements.txt
---

# CI/CD & Railway 배포 계약 (GitHub Actions, start.sh)

## Purpose
- GitHub Actions 워크플로(`salesmap_db_daily.yml`)와 컨테이너 엔트리포인트(`start.sh`)가 DB 스냅샷 생성→GitHub Release 업로드→Railway 재배포로 이어지는 흐름을 명확히 기록한다.
- 리팩토링 시 지켜야 할 배포/런타임 불변 조건과 실패 모드를 한눈에 파악할 수 있게 한다.

## Behavioral Contract
- GitHub Actions 워크플로: `Daily Salesmap DB -> Release -> Railway Redeploy`  
  - 트리거: 매일 18:00 UTC(=KST 03:00) `cron: 0 18 * * *` + `workflow_dispatch`.
  - 러너: `ubuntu-latest`, 권한 `contents: write`.
  - 단계:
    1) `actions/checkout@v4` → 리포지토리 전체를 가져온다.
    2) `actions/setup-python@v5` (`python-version: 3.11`).
    3) `pip install -r requirements.txt`로 의존성 설치.
    4) `python salesmap_first_page_snapshot.py` 실행하여 `salesmap_latest.db` 생성.  
       - 필수 env: `SALESMAP_TOKEN`(secrets).  
       - 로그/체크포인트/백업 디렉터리는 스크립트 인자 그대로 사용.
    5) GitHub Release(태그/이름 `salesmap-db-latest`)에 `salesmap_latest.db` 업로드/치환(`ncipollo/release-action@v1`, `allowUpdates`, `replacesArtifacts` true).
    6) `npm i -g @railway/cli` 후 `railway redeploy --service $RAILWAY_SERVICE_ID --yes`.  
       - env: `RAILWAY_TOKEN`, `RAILWAY_SERVICE_ID` (secrets).
- 컨테이너 엔트리(`start.sh`):
  - 기본 경로: 볼륨 DB `/app/data/salesmap_latest.db`, 앱 참조 `/app/salesmap_latest.db` (심볼릭 링크).
  - 환경변수:
    - `DB_ALWAYS_REFRESH`(기본 1): 1이면 매번 다운로드, 0이면 DB 없을 때만 다운로드.
    - `DB_URL`: DB 다운로드 URL(필수). 미설정 시 에러 종료.
    - `PORT`: uvicorn 포트(기본 8000).
  - 동작:
    1) 다운로드 필요 여부 결정(`DB_ALWAYS_REFRESH=1` 또는 파일 부재 시).
    2) 필요 시 Python 인라인 스크립트로 `DB_URL` 다운로드 → 임시 파일 크기 50MB 미만이면 에러.  
       성공 시 `/app/data/salesmap_latest.db`로 배치.
    3) `/app/salesmap_latest.db`에 심볼릭 링크 생성, `DB_PATH`를 링크 경로로 export.
    4) `python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port $PORT` 실행.

## Invariants (Must Not Break)
- 워크플로 트리거/스케줄: `cron: "0 18 * * *"` 유지(03:00 KST 일 배포).
- 릴리스 아티팩트/태그: 이름·태그 모두 `salesmap-db-latest`, 파일명 `salesmap_latest.db`, `allowUpdates/replacesArtifacts=true`.
- Railway 재배포: CLI 명령 `railway redeploy --service $RAILWAY_SERVICE_ID --yes` (비동의 프롬프트 금지).
- Python 버전 3.11, 의존성 설치 `pip install -r requirements.txt`.
- `start.sh`: DB 링크 경로 `/app/salesmap_latest.db`, `DB_PATH`로 export 후 uvicorn 기동. 다운로드 실패 또는 파일 크기 <50MB 시 즉시 에러 종료.
- 다운로드 조건: `DB_ALWAYS_REFRESH=1` 또는 DB 파일 부재 시에만 다운로드; `DB_URL` 미설정이면 에러.

## Coupling Map
- CI → 스냅샷: `.github/workflows/salesmap_db_daily.yml` → `salesmap_first_page_snapshot.py` (SALESMAP_TOKEN 필요) → 생성된 `salesmap_latest.db`.
- CI → Release: 생성된 DB → GitHub Release(`salesmap-db-latest` 태그/이름, replace artifacts) → 다운로드 URL을 runtime에 주입(DB_URL).
- CI → 배포: Release 완료 후 Railway CLI로 서비스 재배포(secrets: RAILWAY_TOKEN, RAILWAY_SERVICE_ID).
- Runtime(start.sh) → DB 공급: `DB_URL`로 Release asset(또는 외부 URL) 다운로드 → `/app/salesmap_latest.db` symlink → uvicorn `dashboard.server.main:app`.

## Edge Cases & Failure Modes
- `DB_URL` 미지정: start.sh에서 즉시 에러 종료.
- 다운로드 파일 크기 <50MB: 에러 처리(HTML 오류 페이지 등 방지).
- `DB_ALWAYS_REFRESH=0` + 기존 DB 존재: 다운로드 스킵, 기존 파일 사용.
- GitHub Action 실패 시나리오:
  - `SALESMAP_TOKEN` 누락 → 스냅샷 생성 실패.
  - Release 업로드 실패 → downstream 배포는 계속 진행하지만 최신 DB 미반영 위험.
  - `RAILWAY_TOKEN`/`RAILWAY_SERVICE_ID` 누락 → redeploy 단계 실패.
- Uvicorn 포트 충돌: `PORT` 기본 8000, 충돌 시 start.sh는 에러 없이 uvicorn 에러 출력 후 종료.

## Verification
- 수동 워크플로 실행(`workflow_dispatch`) 후:
  - Actions 로그에서 스냅샷 성공, Release 업로드 성공, `railway redeploy` 성공 메시지 확인.
  - Release `salesmap-db-latest`에 최신 `salesmap_latest.db` 존재 여부 확인.
- start.sh 로컬 검증:
  - `DB_URL` 지정 후 `DB_ALWAYS_REFRESH=1`로 실행 → `/app/data/salesmap_latest.db` 생성·링크(`/app/salesmap_latest.db`) 확인, `DB_PATH` 환경변수 확인.
  - `DB_ALWAYS_REFRESH=0` 상태에서 DB 존재 시 “Skip download” 로그 확인.
  - 크기 <50MB 파일을 의도적으로 내려받게 하면 에러 종료되는지 확인.
- Railway 재배포 확인: CLI 로그에 서비스 ID 표시 및 성공 메시지 확인.

## Refactor-Planning Notes (Facts Only)
- CI/CD 파이프라인이 단일 워크플로에 집중되어 있으며 DB 스냅샷/릴리스/배포가 한 잡에서 직렬로 실행됨(분리 시 영향 범위 고려 필요).
- start.sh는 DB 제공/다운로드와 uvicorn 실행을 한 스크립트에 내장해 PATH/ENV 의존도가 높음(ENV 이름 변경 시 컨테이너 기동 실패).
- Release 태그/파일명이 고정(`salesmap-db-latest`, `salesmap_latest.db`); 변경 시 start.sh의 DB_URL 공급 방식이나 외부 자동화가 깨질 수 있음.
