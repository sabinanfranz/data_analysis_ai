#!/usr/bin/env bash
set -euo pipefail

# 1) 볼륨(영구 저장) 위치
VOL_DB="/app/data/salesmap_latest.db"
# 2) 앱이 항상 읽게 만들 고정 위치
APP_DB="/app/salesmap_latest.db"

DB_ALWAYS_REFRESH="${DB_ALWAYS_REFRESH:-1}"

# ✅ Public repo면 이것만 필요
DB_URL="${DB_URL:-}"

download_from_db_url () {
  local tmp="${VOL_DB}.tmp"
  echo "[start.sh] Downloading DB from DB_URL..."
  mkdir -p "$(dirname "$VOL_DB")"
  curl -fL "$DB_URL" -o "$tmp"
  mv "$tmp" "$VOL_DB"
}

# 다운로드 여부
should_download=0
if [ "$DB_ALWAYS_REFRESH" = "1" ]; then
  should_download=1
elif [ ! -f "$VOL_DB" ]; then
  should_download=1
fi

if [ "$should_download" = "1" ]; then
  if [ -z "$DB_URL" ]; then
    echo "ERROR: DB_URL is required (public repo)."
    exit 1
  fi
  download_from_db_url
else
  echo "[start.sh] DB exists and refresh disabled. Skip download."
fi

# 최종 점검
if [ ! -f "$VOL_DB" ]; then
  echo "ERROR: DB not found at $VOL_DB"
  exit 1
fi

# 앱이 읽는 위치로 연결
ln -sf "$VOL_DB" "$APP_DB"
echo "[start.sh] DB ready: $APP_DB -> $VOL_DB"

# DB_PATH를 Railway용으로 고정
export DB_PATH="$APP_DB"

exec python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port "${PORT:-8000}"
