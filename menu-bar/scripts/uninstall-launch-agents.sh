#!/usr/bin/env bash
set -euo pipefail

LAUNCHD_DIR="$HOME/Library/LaunchAgents"
FETCH_LABEL="com.easy-codex-limit-check.fetch"
MENUBAR_LABEL="com.easy-codex-limit-check.menu-bar"
FETCH_PLIST="$LAUNCHD_DIR/$FETCH_LABEL.plist"
MENU_PLIST="$LAUNCHD_DIR/$MENUBAR_LABEL.plist"
BOOTSTRAP_TARGET="gui/$(id -u)"

launchctl bootout "$BOOTSTRAP_TARGET" "$FETCH_PLIST" 2>/dev/null || true
launchctl bootout "$BOOTSTRAP_TARGET" "$MENU_PLIST" 2>/dev/null || true
launchctl unload "$FETCH_PLIST" 2>/dev/null || true
launchctl unload "$MENU_PLIST" 2>/dev/null || true
rm -f "$FETCH_PLIST" "$MENU_PLIST"

echo "Removed:"
echo " - $FETCH_PLIST"
echo " - $MENU_PLIST"
