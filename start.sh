#!/usr/bin/env bash
set -euo pipefail

VOL_DB="/app/data/salesmap_latest.db"
APP_DB="/app/salesmap_latest.db"

# 1) 볼륨에 DB가 있으면 루트로 링크
if [ -f "$VOL_DB" ]; then
  ln -sf "$VOL_DB" "$APP_DB"
fi

# 2) (선택) DB_URL이 있으면 DB가 없을 때만 다운로드
if [ ! -f "$VOL_DB" ] && [ "${DB_URL:-}" != "" ]; then
  echo "Downloading DB from DB_URL..."
  mkdir -p "$(dirname "$VOL_DB")"
  curl -L "$DB_URL" -o "$VOL_DB"
  ln -sf "$VOL_DB" "$APP_DB"
fi

# 3) 최종 점검 (없으면 즉시 실패)
if [ ! -f "$APP_DB" ]; then
  echo "ERROR: DB not found. Put it at $VOL_DB (volume) or set DB_URL."
  exit 1
fi

# 4) FastAPI 실행 (Railway는 PORT 제공)
exec python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port "${PORT:-8000}"