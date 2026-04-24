#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC="$PLUGIN_ROOT/menu-bar/Sources/QuotaMenuBarObjC/main.m"
OUT="${CODEX_QUOTA_MENU_BAR_BIN:-$PLUGIN_ROOT/menu-bar/.build/release/QuotaMenuBar}"

mkdir -p "$(dirname "$OUT")"

SDKROOT_PATH="$(xcrun --sdk macosx --show-sdk-path 2>/dev/null || true)"
ARGS=(
  -fobjc-arc
  -mmacosx-version-min=13.0
  -framework AppKit
  -framework Foundation
)

if [[ -n "$SDKROOT_PATH" ]]; then
  ARGS=(-isysroot "$SDKROOT_PATH" "${ARGS[@]}")
fi

xcrun clang "${ARGS[@]}" "$SRC" -o "$OUT"
chmod +x "$OUT"
echo "$OUT"
