#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_PATH="${CODEX_QUOTA_STATE_PATH:-$HOME/Library/Caches/com.easy-codex-limit-check/state.json}"
CONFIG_PATH="${CODEX_QUOTA_CONFIG_PATH:-$PLUGIN_ROOT/scripts/config.example.json}"
PYTHON_BIN="${CODEX_QUOTA_PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" "$PLUGIN_ROOT/scripts/fetch_quota.py" \
  --config "$CONFIG_PATH" \
  --state-path "$STATE_PATH"
