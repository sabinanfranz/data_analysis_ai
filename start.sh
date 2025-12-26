#!/usr/bin/env bash
set -euo pipefail

VOL_DB="/app/data/salesmap_latest.db"
APP_DB="/app/salesmap_latest.db"

DB_ALWAYS_REFRESH="${DB_ALWAYS_REFRESH:-1}"
DB_URL="${DB_URL:-}"

download_db_with_python () {
  local tmp="${VOL_DB}.tmp"
  echo "[start.sh] Downloading DB with Python..."
  mkdir -p "$(dirname "$VOL_DB")"

  python - <<'PY'
import os, sys, urllib.request

url = os.environ.get("DB_URL")
tmp = os.environ.get("TMP_PATH")

if not url:
    print("ERROR: DB_URL is empty", file=sys.stderr)
    sys.exit(1)

# GitHub releases는 redirect가 있을 수 있어서 기본 opener로 OK
req = urllib.request.Request(url, headers={"User-Agent": "python-urllib"})
with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
    f.write(r.read())

size = os.path.getsize(tmp)
print(f"[start.sh] Downloaded tmp size={size} bytes")
if size < 50_000_000:
    print("ERROR: Downloaded file too small (<50MB). Likely error page.", file=sys.stderr)
    sys.exit(1)
PY
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
  export TMP_PATH="${VOL_DB}.tmp"
  download_db_with_python
else
  echo "[start.sh] DB exists and refresh disabled. Skip download."
fi

if [ ! -f "$VOL_DB" ]; then
  echo "ERROR: DB not found at $VOL_DB"
  exit 1
fi

ln -sf "$VOL_DB" "$APP_DB"
echo "[start.sh] DB ready: $APP_DB -> $VOL_DB"

export DB_PATH="$APP_DB"

exec python -m uvicorn dashboard.server.main:app --host 0.0.0.0 --port "${PORT:-8000}"
