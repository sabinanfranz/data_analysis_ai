#!/usr/bin/env bash
set -euo pipefail

echo "[start.sh] START $(date)"
echo "[start.sh] whoami=$(whoami) pwd=$(pwd)"
echo "[start.sh] DB_ALWAYS_REFRESH=${DB_ALWAYS_REFRESH:-} DB_URL=${DB_URL:-}"
echo "[start.sh] ls -la /app || true"
echo "[start.sh] ls -la /app/data || true"

# 1) 볼륨(영구 저장) 위치
VOL_DB="/app/data/salesmap_latest.db"
# 2) 앱이 항상 읽게 만들 고정 위치
APP_DB="/app/salesmap_latest.db"

DB_ALWAYS_REFRESH="${DB_ALWAYS_REFRESH:-1}"
DB_URL="${DB_URL:-}"

# ---- guard: volume mount check ----
if [ ! -d "/app/data" ]; then
  echo "ERROR: /app/data does not exist. Volume mount is missing or mount path is wrong."
  exit 1
fi

download_from_db_url () {
  local tmp="${VOL_DB}.tmp"
  echo "[start.sh] Downloading DB from DB_URL..."
  mkdir -p "$(dirname "$VOL_DB")"

  # 안전 다운로드: 실패하면 기존 DB 유지
  rm -f "$tmp" || true
  curl -fL "$DB_URL" -o "$tmp"

  # 최소 용량 체크(너 DB가 190MB 근처라서, 너무 작으면 HTML/에러페이지 받은 걸로 판단)
  local bytes
  bytes=$(wc -c < "$tmp" | tr -d ' ')
  echo "[start.sh] Downloaded tmp size=${bytes} bytes"
  if [ "$bytes" -lt 50000000 ]; then
    echo "ERROR: Downloaded file is too small (<50MB). Likely got an error page."
    echo "[start.sh] First 200 bytes:"
    head -c 200 "$tmp" || true
    exit 1
  fi

  mv "$tmp" "$VOL_DB"
  echo "[start.sh] DB saved to $VOL_DB"
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
echo "[start.sh] export DB_PATH=$DB_PATH"

# uvicorn 실행 전 체크 로그
python -V
echo "[start.sh] launching uvicorn..."

exec python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port "${PORT:-8000}"