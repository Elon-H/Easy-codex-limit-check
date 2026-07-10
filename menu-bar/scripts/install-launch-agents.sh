#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
FETCH_LABEL="com.easy-codex-limit-check.fetch"
MENUBAR_LABEL="com.easy-codex-limit-check.menu-bar"
APPROVAL_LABEL="com.easy-codex-limit-check.approval-watcher"
FETCH_PLIST="$LAUNCHD_DIR/$FETCH_LABEL.plist"
MENU_PLIST="$LAUNCHD_DIR/$MENUBAR_LABEL.plist"
APPROVAL_PLIST="$LAUNCHD_DIR/$APPROVAL_LABEL.plist"
STATE_PATH="${CODEX_QUOTA_STATE_PATH:-$HOME/Library/Caches/com.easy-codex-limit-check/state.json}"
APPROVAL_STATE_PATH="${CODEX_APPROVAL_STATE_PATH:-$HOME/Library/Caches/com.easy-codex-limit-check/approval_state.json}"
APPROVAL_DECISIONS_PATH="${CODEX_APPROVAL_DECISIONS_PATH:-$HOME/Library/Caches/com.easy-codex-limit-check/approval_decisions.jsonl}"
CONFIG_PATH="${CODEX_QUOTA_CONFIG_PATH:-$PLUGIN_ROOT/scripts/config.example.json}"
RUNTIME_DIR="${CODEX_QUOTA_RUNTIME_DIR:-$HOME/Library/Application Support/com.easy-codex-limit-check}"
RUNTIME_BIN_DIR="$RUNTIME_DIR/bin"
RUNTIME_SCRIPT_DIR="$RUNTIME_DIR/scripts"
MENU_BIN="$RUNTIME_BIN_DIR/QuotaMenuBar"
RUNTIME_FETCH="$RUNTIME_SCRIPT_DIR/fetch_quota.py"
RUNTIME_APPROVAL_WATCHER="$RUNTIME_SCRIPT_DIR/watch_approvals.py"
RUNTIME_CONFIG="$RUNTIME_DIR/config.json"
RUNTIME_RUN_FETCH="$RUNTIME_SCRIPT_DIR/run_fetch_quota.sh"
RUNTIME_RUN_APPROVAL_WATCHER="$RUNTIME_SCRIPT_DIR/run_approval_watcher.sh"
BUILD_SCRIPT="$PLUGIN_ROOT/menu-bar/scripts/build_objc_menu_bar.sh"
BUILT_MENU_BIN="${CODEX_QUOTA_MENU_BAR_BIN:-$PLUGIN_ROOT/menu-bar/.build/release/QuotaMenuBar}"
BOOTSTRAP_TARGET="gui/$(id -u)"

choose_python_bin() {
  local candidate resolved
  for candidate in \
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "python3" \
    "/usr/bin/python3"; do
    if [[ "$candidate" == */* ]]; then
      [[ -x "$candidate" ]] || continue
      resolved="$candidate"
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
      [[ -n "$resolved" ]] || continue
    fi

    if "$resolved" --version >/dev/null 2>&1; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

choose_codex_bin_dir() {
  local candidate resolved
  for candidate in \
    "/Applications/ChatGPT.app/Contents/Resources/codex" \
    "/Applications/Codex.app/Contents/Resources/codex"; do
    if [[ -x "$candidate" ]]; then
      dirname "$candidate"
      return 0
    fi
  done

  resolved="$(command -v codex 2>/dev/null || true)"
  if [[ -n "$resolved" && -x "$resolved" ]]; then
    dirname "$resolved"
    return 0
  fi
  return 1
}

PYTHON_BIN="${CODEX_QUOTA_PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if ! PYTHON_BIN="$(choose_python_bin)"; then
    echo "No usable python3 found. Set CODEX_QUOTA_PYTHON_BIN to a working Python 3 executable." >&2
    exit 1
  fi
fi

LAUNCH_PATH="$PATH"
if CODEX_BIN_DIR="$(choose_codex_bin_dir)"; then
  case ":$LAUNCH_PATH:" in
    *":$CODEX_BIN_DIR:"*) ;;
    *) LAUNCH_PATH="$CODEX_BIN_DIR:$LAUNCH_PATH" ;;
  esac
fi

mkdir -p "$LAUNCHD_DIR"
mkdir -p "$(dirname "$STATE_PATH")"
mkdir -p "$(dirname "$APPROVAL_STATE_PATH")" "$(dirname "$APPROVAL_DECISIONS_PATH")"
mkdir -p "$RUNTIME_BIN_DIR" "$RUNTIME_SCRIPT_DIR"

if [[ -z "${CODEX_QUOTA_MENU_BAR_BIN:-}" ]]; then
  "$BUILD_SCRIPT" >/dev/null
elif [[ ! -x "$BUILT_MENU_BIN" ]]; then
  "$BUILD_SCRIPT" >/dev/null
fi

cp "$BUILT_MENU_BIN" "$MENU_BIN"
cp "$PLUGIN_ROOT/scripts/fetch_quota.py" "$RUNTIME_FETCH"
cp "$PLUGIN_ROOT/scripts/watch_approvals.py" "$RUNTIME_APPROVAL_WATCHER"
cp "$CONFIG_PATH" "$RUNTIME_CONFIG"
chmod +x "$MENU_BIN"

cat > "$RUNTIME_RUN_FETCH" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_PATH="${CODEX_QUOTA_STATE_PATH:-$HOME/Library/Caches/com.easy-codex-limit-check/state.json}"
CONFIG_PATH="${CODEX_QUOTA_CONFIG_PATH:-$RUNTIME_DIR/config.json}"
PYTHON_BIN="${CODEX_QUOTA_PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" "$RUNTIME_DIR/scripts/fetch_quota.py" \
  --config "$CONFIG_PATH" \
  --state-path "$STATE_PATH"
SH
chmod +x "$RUNTIME_RUN_FETCH"

cat > "$RUNTIME_RUN_APPROVAL_WATCHER" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPROVAL_STATE_PATH="${CODEX_APPROVAL_STATE_PATH:-$HOME/Library/Caches/com.easy-codex-limit-check/approval_state.json}"
APPROVAL_DECISIONS_PATH="${CODEX_APPROVAL_DECISIONS_PATH:-$HOME/Library/Caches/com.easy-codex-limit-check/approval_decisions.jsonl}"
CONFIG_PATH="${CODEX_QUOTA_CONFIG_PATH:-$RUNTIME_DIR/config.json}"
PYTHON_BIN="${CODEX_QUOTA_PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" "$RUNTIME_DIR/scripts/watch_approvals.py" \
  --config "$CONFIG_PATH" \
  --state-path "$APPROVAL_STATE_PATH" \
  --decisions-path "$APPROVAL_DECISIONS_PATH"
SH
chmod +x "$RUNTIME_RUN_APPROVAL_WATCHER"

cat > "$FETCH_PLIST" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.easy-codex-limit-check.fetch</string>
  <key>ProgramArguments</key>
  <array>
    <string>__RUN_FETCH__</string>
  </array>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CODEX_QUOTA_STATE_PATH</key>
    <string>__STATE_PATH__</string>
    <key>CODEX_QUOTA_PLUGIN_PATH</key>
    <string>__PLUGIN_ROOT__</string>
    <key>CODEX_QUOTA_CONFIG_PATH</key>
    <string>__CONFIG_PATH__</string>
    <key>CODEX_QUOTA_PYTHON_BIN</key>
    <string>__PYTHON_BIN__</string>
    <key>PATH</key>
    <string>__PATH__</string>
  </dict>
  <key>StandardOutPath</key>
  <string>__LOG_STDOUT__</string>
  <key>StandardErrorPath</key>
  <string>__LOG_STDERR__</string>
</dict>
</plist>
PLIST

cat > "$APPROVAL_PLIST" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.easy-codex-limit-check.approval-watcher</string>
  <key>ProgramArguments</key>
  <array>
    <string>__RUN_APPROVAL_WATCHER__</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CODEX_APPROVAL_STATE_PATH</key>
    <string>__APPROVAL_STATE_PATH__</string>
    <key>CODEX_APPROVAL_DECISIONS_PATH</key>
    <string>__APPROVAL_DECISIONS_PATH__</string>
    <key>CODEX_QUOTA_PLUGIN_PATH</key>
    <string>__PLUGIN_ROOT__</string>
    <key>CODEX_QUOTA_CONFIG_PATH</key>
    <string>__CONFIG_PATH__</string>
    <key>CODEX_QUOTA_PYTHON_BIN</key>
    <string>__PYTHON_BIN__</string>
    <key>PATH</key>
    <string>__PATH__</string>
  </dict>
  <key>StandardOutPath</key>
  <string>__APPROVAL_STDOUT__</string>
  <key>StandardErrorPath</key>
  <string>__APPROVAL_STDERR__</string>
</dict>
</plist>
PLIST

cat > "$MENU_PLIST" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.easy-codex-limit-check.menu-bar</string>
  <key>ProgramArguments</key>
  <array>
    <string>__MENU_BIN__</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CODEX_QUOTA_STATE_PATH</key>
    <string>__STATE_PATH__</string>
    <key>CODEX_QUOTA_PLUGIN_PATH</key>
    <string>__PLUGIN_ROOT__</string>
    <key>CODEX_QUOTA_FETCH_SCRIPT</key>
    <string>__RUN_FETCH__</string>
    <key>CODEX_QUOTA_PYTHON_BIN</key>
    <string>__PYTHON_BIN__</string>
    <key>CODEX_APPROVAL_STATE_PATH</key>
    <string>__APPROVAL_STATE_PATH__</string>
    <key>CODEX_APPROVAL_DECISIONS_PATH</key>
    <string>__APPROVAL_DECISIONS_PATH__</string>
    <key>PATH</key>
    <string>__PATH__</string>
  </dict>
  <key>StandardOutPath</key>
  <string>__MENU_STDOUT__</string>
  <key>StandardErrorPath</key>
  <string>__MENU_STDERR__</string>
</dict>
</plist>
PLIST

LOG_DIR="$HOME/Library/Logs/com.easy-codex-limit-check"
mkdir -p "$LOG_DIR"

sed -i '' "s#__RUN_FETCH__#$RUNTIME_RUN_FETCH#g" "$FETCH_PLIST"
sed -i '' "s#__STATE_PATH__#$STATE_PATH#g" "$FETCH_PLIST"
sed -i '' "s#__CONFIG_PATH__#$RUNTIME_CONFIG#g" "$FETCH_PLIST"
sed -i '' "s#__PYTHON_BIN__#$PYTHON_BIN#g" "$FETCH_PLIST"
sed -i '' "s#__PLUGIN_ROOT__#$PLUGIN_ROOT#g" "$FETCH_PLIST"
sed -i '' "s#__LOG_STDOUT__#$LOG_DIR/fetch.stdout.log#g" "$FETCH_PLIST"
sed -i '' "s#__LOG_STDERR__#$LOG_DIR/fetch.stderr.log#g" "$FETCH_PLIST"
sed -i '' "s#__RUN_APPROVAL_WATCHER__#$RUNTIME_RUN_APPROVAL_WATCHER#g" "$APPROVAL_PLIST"
sed -i '' "s#__APPROVAL_STATE_PATH__#$APPROVAL_STATE_PATH#g" "$APPROVAL_PLIST"
sed -i '' "s#__APPROVAL_DECISIONS_PATH__#$APPROVAL_DECISIONS_PATH#g" "$APPROVAL_PLIST"
sed -i '' "s#__CONFIG_PATH__#$RUNTIME_CONFIG#g" "$APPROVAL_PLIST"
sed -i '' "s#__PYTHON_BIN__#$PYTHON_BIN#g" "$APPROVAL_PLIST"
sed -i '' "s#__PLUGIN_ROOT__#$PLUGIN_ROOT#g" "$APPROVAL_PLIST"
sed -i '' "s#__APPROVAL_STDOUT__#$LOG_DIR/approval.stdout.log#g" "$APPROVAL_PLIST"
sed -i '' "s#__APPROVAL_STDERR__#$LOG_DIR/approval.stderr.log#g" "$APPROVAL_PLIST"
sed -i '' "s#__MENU_BIN__#$MENU_BIN#g" "$MENU_PLIST"
sed -i '' "s#__RUN_FETCH__#$RUNTIME_RUN_FETCH#g" "$MENU_PLIST"
sed -i '' "s#__STATE_PATH__#$STATE_PATH#g" "$MENU_PLIST"
sed -i '' "s#__PYTHON_BIN__#$PYTHON_BIN#g" "$MENU_PLIST"
sed -i '' "s#__APPROVAL_STATE_PATH__#$APPROVAL_STATE_PATH#g" "$MENU_PLIST"
sed -i '' "s#__APPROVAL_DECISIONS_PATH__#$APPROVAL_DECISIONS_PATH#g" "$MENU_PLIST"
sed -i '' "s#__PLUGIN_ROOT__#$PLUGIN_ROOT#g" "$MENU_PLIST"
sed -i '' "s#__MENU_STDOUT__#$LOG_DIR/menu.stdout.log#g" "$MENU_PLIST"
sed -i '' "s#__MENU_STDERR__#$LOG_DIR/menu.stderr.log#g" "$MENU_PLIST"
sed -i '' "s#__PATH__#${LAUNCH_PATH//\//\\/}#g" "$FETCH_PLIST" "$APPROVAL_PLIST" "$MENU_PLIST"

export CODEX_QUOTA_STATE_PATH="$STATE_PATH"
export CODEX_QUOTA_PLUGIN_PATH="$PLUGIN_ROOT"

launchctl bootout "$BOOTSTRAP_TARGET" "$FETCH_PLIST" 2>/dev/null || true
launchctl bootout "$BOOTSTRAP_TARGET" "$APPROVAL_PLIST" 2>/dev/null || true
launchctl bootout "$BOOTSTRAP_TARGET" "$MENU_PLIST" 2>/dev/null || true
launchctl unload "$FETCH_PLIST" 2>/dev/null || true
launchctl unload "$APPROVAL_PLIST" 2>/dev/null || true
launchctl unload "$MENU_PLIST" 2>/dev/null || true
launchctl bootstrap "$BOOTSTRAP_TARGET" "$FETCH_PLIST"
launchctl bootstrap "$BOOTSTRAP_TARGET" "$APPROVAL_PLIST"
launchctl bootstrap "$BOOTSTRAP_TARGET" "$MENU_PLIST"
launchctl kickstart -k "$BOOTSTRAP_TARGET/$FETCH_LABEL"
launchctl kickstart -k "$BOOTSTRAP_TARGET/$APPROVAL_LABEL"
launchctl kickstart -k "$BOOTSTRAP_TARGET/$MENUBAR_LABEL"

echo "Installed launch agents:"
echo " - $FETCH_PLIST"
echo " - $APPROVAL_PLIST"
echo " - $MENU_PLIST"
echo "Runtime:"
echo " - $RUNTIME_DIR"
