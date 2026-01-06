---
title: CI/CD & Railway 배포 계약
last_synced: 2026-01-06
sync_source:
  - .github/workflows/salesmap_db_daily.yml
  - start.sh
  - salesmap_first_page_snapshot.py
  - requirements.txt
---

## Purpose
- GitHub Actions 워크플로(`salesmap_db_daily.yml`)와 컨테이너 엔트리(`start.sh`)의 배포 흐름과 불변 조건을 정리해 리팩토링/배포 시 준수사항을 명확히 한다.

## Behavioral Contract
- GitHub Actions: 매일 18:00 UTC(`cron: "0 18 * * *"`) + `workflow_dispatch`로 트리거. 단계:
  1) checkout → Python 3.11 세팅.
  2) `pip install -r requirements.txt`.
  3) `python salesmap_first_page_snapshot.py` 실행(필수 env `SALESMAP_TOKEN`), DB 생성.
  4) Release `salesmap-db-latest`(태그/이름 동일)에 `salesmap_latest.db` 업로드(`allowUpdates`, `replacesArtifacts` true).
  5) `railway redeploy --service $RAILWAY_SERVICE_ID --yes`(`RAILWAY_TOKEN`, `RAILWAY_SERVICE_ID` 필요).
- 컨테이너(start.sh):
  - 환경: `DB_ALWAYS_REFRESH`(기본 1), `DB_URL`(필수), `PORT`(기본 8000).
  - 동작: 필요 시 Python 인라인 스크립트로 `DB_URL` 다운로드(50MB 미만이면 에러) → `/app/data/salesmap_latest.db` 저장 → `/app/salesmap_latest.db` 심볼릭 링크 → `DB_PATH` export → `uvicorn dashboard.server.main:app --host 0.0.0.0 --port $PORT`.

## Invariants (Must Not Break)
- 워크플로 스케줄 `cron: "0 18 * * *"`, Release 이름/태그 `salesmap-db-latest`, 아티팩트 이름 `salesmap_latest.db` 유지.
- Railway 재배포 명령은 `railway redeploy --service $RAILWAY_SERVICE_ID --yes`(비동의 프롬프트 없음)이며, secrets(`RAILWAY_TOKEN`, `RAILWAY_SERVICE_ID`)가 필요하다.
- start.sh는 DB 크기 50MB 미만이면 실패 처리, `DB_URL` 미설정 시 에러 종료한다. 링크 경로는 `/app/salesmap_latest.db`로 고정.
- Python 버전 3.11 및 `pip install -r requirements.txt` 절차는 변경하지 않는다.

## Coupling Map
- CI → 스냅샷: 워크플로 → `salesmap_first_page_snapshot.py` → `salesmap_latest.db`.
- CI → Release: 생성된 DB → GitHub Release(`salesmap-db-latest`) → 런타임 `DB_URL`로 다운로드.
- CI → 배포: Release 후 Railway CLI 재배포(secrets 필요).
- 런타임: `start.sh`가 DB를 다운로드/링크 후 FastAPI(`dashboard.server.main:app`)를 기동한다.

## Edge Cases & Failure Modes
- `DB_URL` 누락 또는 파일 크기 <50MB → start.sh 에러 종료.
- `DB_ALWAYS_REFRESH=0`이고 DB가 이미 있으면 다운로드 스킵 → 오래된 DB를 계속 사용할 수 있음.
- Actions secrets(`SALESMAP_TOKEN`, `RAILWAY_TOKEN`, `RAILWAY_SERVICE_ID`) 누락 시 해당 단계 실패로 최신 DB/배포가 중단된다.
- Release 업로드 실패 시 redeploy는 진행되더라도 최신 DB가 배포되지 않는다.

## Verification
- `workflow_dispatch`로 워크플로 수동 실행 후 스텝 로그에서 스냅샷/Release 업로드/railway redeploy 성공 여부를 확인한다.
- Release `salesmap-db-latest`에 최신 타임스탬프의 `salesmap_latest.db`가 올라갔는지 확인한다.
- start.sh 로컬 실행 시 `/app/data/salesmap_latest.db` 생성 및 `/app/salesmap_latest.db` 링크, `DB_PATH` 환경변수 설정이 되는지 확인한다.
- `DB_ALWAYS_REFRESH=0` 설정에서 기존 DB가 있을 때 다운로드가 스킵되는지, 크기 <50MB 테스트 파일로 오류 처리되는지 확인한다.

## Refactor-Planning Notes (Facts Only)
- 스냅샷/Release/재배포가 단일 워크플로에 직렬로 묶여 있어 한 단계 실패 시 전체가 중단된다.
- DB 경로와 Release 이름이 코드/스크립트/런타임 환경변수에 하드코딩되어 있어 변경 시 다중 수정이 필요하다.
- start.sh는 DB 다운로드와 앱 기동을 한 스크립트에 결합해 있어 DB 공급 방식을 바꾸면 스크립트를 함께 수정해야 한다.
