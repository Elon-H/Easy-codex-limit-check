#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_PATH="${CODEX_QUOTA_STATE_PATH:-$HOME/Library/Caches/com.easy-codex-limit-check/state.json}"
BUILD_SCRIPT="$PLUGIN_ROOT/menu-bar/scripts/build_objc_menu_bar.sh"
BIN_PATH="${CODEX_QUOTA_MENU_BAR_BIN:-$PLUGIN_ROOT/menu-bar/.build/release/QuotaMenuBar}"

if [[ ! -x "$BIN_PATH" ]]; then
  if [[ -z "${CODEX_QUOTA_MENU_BAR_BIN:-}" && -x "$BUILD_SCRIPT" ]]; then
    "$BUILD_SCRIPT" >/dev/null
  fi
fi

if [[ ! -x "$BIN_PATH" ]]; then
  BIN_PATH="${CODEX_QUOTA_MENU_BAR_BIN:-$PLUGIN_ROOT/menu-bar/.build/debug/QuotaMenuBar}"
fi

if [[ ! -x "$BIN_PATH" ]]; then
  echo "QuotaMenuBar binary not found. Build first: cd \"$PLUGIN_ROOT/menu-bar\" && scripts/build_objc_menu_bar.sh" >&2
  exit 1
fi

export CODEX_QUOTA_STATE_PATH="$STATE_PATH"
export CODEX_QUOTA_PLUGIN_PATH="$PLUGIN_ROOT"
exec "$BIN_PATH"
