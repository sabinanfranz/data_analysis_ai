---
title: CI/CD & Railway 배포 계약
last_synced: 2026-02-04
sync_source:
  - .github/workflows/salesmap_db_daily.yml
  - start.sh
  - salesmap_first_page_snapshot.py
  - requirements.txt
---

## Purpose
- GitHub Actions 워크플로(`salesmap_db_daily.yml`)와 컨테이너 엔트리(`start.sh`)의 배포 흐름과 불변 조건을 SSOT로 기록한다.

## Behavioral Contract
### GitHub Actions (salesmap_db_daily.yml)
- 트리거: cron `0 18 * * *`(매일 03:00 KST) + `workflow_dispatch`.
- 환경: Python 3.11, `pip install -r requirements.txt`.
- 스텝 순서:
  1) Checkout
  2) Setup Python 3.11
  3) Install deps: `pip install -r requirements.txt`
  4) Build DB: `python salesmap_first_page_snapshot.py --db-path salesmap_latest.db --log-dir logs --checkpoint-dir logs/checkpoints --backup-dir backups --keep-backups 7` (env `SALESMAP_TOKEN` 필요)
  5) Release 업로드: tag/name `salesmap-db-latest`, artifact `salesmap_latest.db`, `allowUpdates`/`replacesArtifacts`/`artifactErrorsFailBuild` true
  6) Railway redeploy: `railway redeploy --service $RAILWAY_SERVICE_ID --yes` (env `RAILWAY_TOKEN` 필요)

### Runtime / start.sh (Railway 컨테이너)
- Env: `DB_URL`(필수), `DB_ALWAYS_REFRESH`(default 1), `PORT`(default 8000).
- 동작: 필요 시 DB 다운로드(파이썬 내장 스크립트, 50MB 미만이면 에러) → `/app/data/salesmap_latest.db` 저장 → `/app/salesmap_latest.db` 심링크 → `DB_PATH` export → `python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port ${PORT:-8000}`.

## Invariants (Must Not Break)
- cron 스케줄 `0 18 * * *`, Release tag/name `salesmap-db-latest`, artifact 이름 `salesmap_latest.db` 유지.
- Railway redeploy 명령은 반드시 `railway redeploy --service $RAILWAY_SERVICE_ID --yes`; secrets `RAILWAY_TOKEN`, `RAILWAY_SERVICE_ID` 필수.
- start.sh: DB_URL 미설정 또는 다운로드 크기 <50MB → 오류 종료; 심링크 경로 `/app/salesmap_latest.db` 고정; DB_ALWAYS_REFRESH=0이면 기존 파일이 있으면 다운로드 스킵.
- Python 3.11 + `pip install -r requirements.txt` 설치 단계 유지.

## Coupling Map
- CI → 스냅샷: GH Actions → `salesmap_first_page_snapshot.py` → `salesmap_latest.db`.
- CI → Release: DB → GitHub Release(salesmap-db-latest) → 런타임 `DB_URL`로 다운로드.
- CI → 배포: Release 후 Railway CLI redeploy (tokens 필요).
- 런타임: start.sh가 DB 다운로드/검증/심링크 후 FastAPI(`dashboard.server.main:app`) 기동.

## Edge Cases & Failure Modes
- `DB_URL` 누락/잘못된 URL/50MB 미만 파일 → start.sh 즉시 종료.
- `DB_ALWAYS_REFRESH=0` + 기존 DB 존재 → 다운로드 스킵 → 오래된 DB 사용 가능성.
- GH secrets(`SALESMAP_TOKEN`, `RAILWAY_TOKEN`, `RAILWAY_SERVICE_ID`) 누락 → 스텝 실패, 최신 DB/배포 중단.
- Release 업로드 실패 시 redeploy가 수행돼도 최신 DB가 배포되지 않는다.

## Verification
- `workflow_dispatch` 실행 후 Actions 로그에서 snapshot→Release 업로드→Railway redeploy 성공 여부 확인.
- Release `salesmap-db-latest`에 최신 `salesmap_latest.db`가 있는지 확인(타임스탬프/크기).
- start.sh 로컬 실행 시 `/app/data/salesmap_latest.db` 생성, `/app/salesmap_latest.db` 심링크, DB_PATH 설정 확인. 50MB 미만 파일로 오류 처리되는지 테스트.
- `DB_ALWAYS_REFRESH=0` 설정에서 기존 DB 존재 시 다운로드가 스킵되는지 확인.

## Refactor-Planning Notes (Facts Only)
- 스냅샷→Release→재배포가 하나의 워크플로에 직렬로 묶여 단일 실패 지점이 된다.
- DB 경로와 Release 이름이 코드/스크립트/런타임에 하드코딩되어 있어 변경 시 다중 수정 필요.
- start.sh가 다운로드/검증/기동을 단일 스크립트에 결합해 DB 공급 방식을 바꾸려면 스크립트도 수정해야 한다.
