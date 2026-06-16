# Easy Codex Limit Check

macOS menu-bar widget for checking Codex Pro `5h` and `Weekly` rate-limit remaining percentages from your local Codex login.

It shows the same kind of data as Codex's **Rate limits remaining** panel in a compact native menu-bar view:

```text
5h  [ 69% ]  03:05    Week  [ 95% ]  4/29
```

The short quota bars show the percentage inside the bar and shift from green toward orange/red as the quota gets low.

The menu dropdown also shows model-specific limits such as `GPT-5.3-Codex-Spark`.

## What It Does

- Uses the documented Codex App Server JSON-RPC interface over local stdio.
- Falls back to `https://chatgpt.com/backend-api/wham/usage` when App Server is unavailable.
- Writes a normalized local state file.
- Runs a native macOS menu-bar app that updates every 30 seconds.
- Displays `5h` and `Week` in one line with short remaining-quota bars, inside-bar percentage labels, compact reset time/date, and low-quota colors.
- Watches Codex approval requests and lets you approve or deny them from the menu bar.
- Installs LaunchAgents so the fetcher refreshes every 60 seconds and the menu-bar app starts on login.

## Install

Clone the repository, then run:

```bash
cd easy-codex-limit-check
./install.sh
```

Requirements:

- macOS
- Codex desktop app or Codex CLI already logged in
- a working Python 3 executable; the installer prefers Codex's bundled runtime Python when available
- Xcode Command Line Tools with `clang`

No OpenAI API key is required for the default Codex Pro limit mode.

## Uninstall

```bash
cd easy-codex-limit-check
./uninstall.sh
```

This removes the LaunchAgents. Runtime files may remain under:

```text
~/Library/Application Support/com.easy-codex-limit-check/
~/Library/Caches/com.easy-codex-limit-check/
~/Library/Logs/com.easy-codex-limit-check/
```

## Data Source

The default provider is `app_server`.

It starts Codex App Server locally over stdio and calls:

```text
account/rateLimits/read
```

The response returns used percentages. This project converts them to remaining percentages:

```text
remaining_percent = 100 - used_percent
```

The legacy `codex_wham` provider still exists as a compatibility fallback for older Codex versions or App Server failures. That fallback uses `https://chatgpt.com/backend-api/wham/usage`.

The menu-bar app does not use App Server WebSocket transport. WebSocket is not needed for the local Mac widget and should not be exposed to a network without authentication.

## Approval Watcher

When a Codex thread is waiting on approval, the menu-bar item adds a compact approval marker before the quota display, for example:

```text
审批 1  5h [69%] 03:05  Week [95%] 4/29
```

The watcher first tries the local App Server proxy and falls back to a local stdio App Server process. When App Server can route approval requests to this watcher, the menu supports direct actions for:

```text
item/commandExecution/requestApproval
item/fileChange/requestApproval
item/permissions/requestApproval
execCommandApproval
applyPatchApproval
```

The menu can approve, approve for session, deny, or cancel supported command/file-change approvals. Permission approvals can be granted for the turn, granted for the session, or denied. The app never auto-approves a request.

For Codex Desktop builds that do not expose an App Server control socket, the watcher also scans recent local rollout files for pending `require_escalated` tool calls. Those fallback detections still trigger the orange menu-bar approval indicator and a notification, but they only offer `Open Codex` because the active desktop client owns the actual approve/deny prompt.

## Privacy

In the default `app_server` mode, Codex manages auth through the local App Server process.

The legacy `codex_wham` fallback reads `~/.codex/auth.json` only to make the fallback usage request.

It does not write your token, email, account id, or user id to the state file.

The local state file is:

```text
~/Library/Caches/com.easy-codex-limit-check/state.json
```

Approval state and menu decisions are stored locally:

```text
~/Library/Caches/com.easy-codex-limit-check/approval_state.json
~/Library/Caches/com.easy-codex-limit-check/approval_decisions.jsonl
```

Example shape:

```json
{
  "rate_limits": [
    {
      "name": "Rate limits remaining",
      "five_h": {
        "remaining_percent": 69,
        "reset_at": "2026-04-24T19:05:30Z"
      },
      "week": {
        "remaining_percent": 95,
        "reset_at": "2026-04-29T03:06:20Z"
      }
    }
  ]
}
```

## Manual Refresh

```bash
python3 ./scripts/fetch_quota.py \
  --config ./scripts/config.example.json \
  --state-path "$HOME/Library/Caches/com.easy-codex-limit-check/state.json"
```

Dry run:

```bash
python3 ./scripts/fetch_quota.py --config ./scripts/config.example.json --dry-run
```

## Troubleshooting

If updates stop after installing Xcode, check:

```bash
python3 --version
```

If it prints an Xcode license error, reinstall with `./install.sh`; the installer now records a working Python path in the LaunchAgent. You can also fix the system toolchain globally from Terminal:

```bash
sudo xcodebuild -license accept
```

## Development

Build the menu-bar binary:

```bash
cd menu-bar
scripts/build_objc_menu_bar.sh
```

Run without installing LaunchAgents:

```bash
cd menu-bar
scripts/run_menu_bar.sh
```

Validate scripts:

```bash
bash -n menu-bar/scripts/*.sh
PYTHONPYCACHEPREFIX=/tmp/eclc-pycache python3 -m py_compile scripts/fetch_quota.py scripts/watch_approvals.py
python3 -m unittest discover -s tests
```

## Repository Description

Use this for GitHub:

```text
macOS menu-bar widget for checking Codex Pro 5h and weekly rate-limit remaining percentages with compact in-bar quota indicators.
```

Suggested topics:

```text
codex openai chatgpt macos menu-bar rate-limit quota launchagent
```

## License

MIT
