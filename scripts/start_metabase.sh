#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="/tmp/bitrix-metabase-runtime"
mkdir -p "$RUNTIME_ROOT/vendor" "$RUNTIME_ROOT/data"

if [[ ! -f "$RUNTIME_ROOT/vendor/metabase.jar" || "$ROOT/vendor/metabase.jar" -nt "$RUNTIME_ROOT/vendor/metabase.jar" ]]; then
  cp "$ROOT/vendor/metabase.jar" "$RUNTIME_ROOT/vendor/metabase.jar"
fi

if [[ -f "$ROOT/data/bitrix24_demo.sqlite" ]]; then
  cp "$ROOT/data/bitrix24_demo.sqlite" "$RUNTIME_ROOT/data/bitrix24_demo.sqlite"
fi

JAVA_BIN="$RUNTIME_ROOT/vendor/jre/bin/java"
METABASE_JAR="$RUNTIME_ROOT/vendor/metabase.jar"
APP_DB_DIR="$RUNTIME_ROOT/data/metabase-app"
LOG_DIR="$ROOT/logs"
PORT="${MB_JETTY_PORT:-3000}"

if [[ ! -x "$JAVA_BIN" || ! -f "$METABASE_JAR" ]]; then
  if [[ ! -x "$ROOT/vendor/jre/bin/java" || ! -f "$ROOT/vendor/metabase.jar" ]]; then
    echo "Runtime is missing. Run ./scripts/download_runtime.sh first." >&2
    exit 1
  fi
  cp -R "$ROOT/vendor/jre" "$RUNTIME_ROOT/vendor/jre"
fi

mkdir -p "$APP_DB_DIR" "$LOG_DIR"

export MB_JETTY_PORT="$PORT"
export MB_DB_TYPE="h2"
export MB_DB_FILE="$APP_DB_DIR/metabase.db"
export MB_SITE_LOCALE="ru"
export MB_ANON_TRACKING_ENABLED="false"

echo "Starting Metabase at http://localhost:$PORT"
echo "Logs: $LOG_DIR/metabase.log"

cd "$RUNTIME_ROOT"
exec "$JAVA_BIN" --add-opens java.base/java.nio=ALL-UNNAMED \
  -jar "$METABASE_JAR" 2>&1 | tee "$LOG_DIR/metabase.log"
