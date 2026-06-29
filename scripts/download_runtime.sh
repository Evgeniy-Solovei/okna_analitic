#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$ROOT/vendor"
METABASE_JAR="$VENDOR_DIR/metabase.jar"
JRE_DIR="$VENDOR_DIR/jre"

mkdir -p "$VENDOR_DIR"

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) ADOPTIUM_ARCH="aarch64" ;;
  x86_64) ADOPTIUM_ARCH="x64" ;;
  *)
    echo "Unsupported macOS architecture: $ARCH" >&2
    exit 1
    ;;
esac

if [[ ! -x "$JRE_DIR/bin/java" ]]; then
  TMP_TGZ="$VENDOR_DIR/temurin-jre21.tar.gz"
  echo "Downloading Eclipse Temurin JRE 21 for macOS $ADOPTIUM_ARCH..."
  curl -L \
    "https://api.adoptium.net/v3/binary/latest/21/ga/mac/${ADOPTIUM_ARCH}/jre/hotspot/normal/eclipse?project=jdk" \
    -o "$TMP_TGZ"

  rm -rf "$JRE_DIR" "$VENDOR_DIR"/jdk-*
  mkdir -p "$JRE_DIR"
  tar -xzf "$TMP_TGZ" -C "$VENDOR_DIR"

  JAVA_HOME_FOUND="$(find "$VENDOR_DIR" -path '*/Contents/Home/bin/java' -type f | head -n 1)"
  if [[ -z "$JAVA_HOME_FOUND" ]]; then
    echo "Could not find java binary after extracting JRE." >&2
    exit 1
  fi

  JAVA_HOME_DIR="$(cd "$(dirname "$JAVA_HOME_FOUND")/.." && pwd)"
  rm -rf "$JRE_DIR"
  mv "$JAVA_HOME_DIR" "$JRE_DIR"
  rm -rf "$VENDOR_DIR"/*.jdk "$VENDOR_DIR"/jdk-* "$TMP_TGZ"
fi

if [[ ! -f "$METABASE_JAR" ]]; then
  echo "Downloading Metabase OSS JAR..."
  curl -L "https://downloads.metabase.com/latest/metabase.jar" -o "$METABASE_JAR"
fi

"$JRE_DIR/bin/java" -version
echo "Metabase JAR: $METABASE_JAR"

