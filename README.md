# Easy Codex Limit Check

macOS menu-bar widget for checking Codex Pro `5h` and `Weekly` rate-limit remaining percentages from your local Codex login.

It shows the same kind of data as Codex's **Rate limits remaining** panel:

```text
5h 69% 03:05 | W 95% Apr 29
```

The menu dropdown also shows model-specific limits such as `GPT-5.3-Codex-Spark`.

## What It Does

- Reads your local Codex login token from `~/.codex/auth.json`.
- Fetches Codex/ChatGPT usage from `https://chatgpt.com/backend-api/wham/usage`.
- Writes a normalized local state file.
- Runs a native macOS menu-bar app that updates every 30 seconds.
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
- `python3`
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

The default provider is `codex_wham`.

It uses the same signed-in Codex/ChatGPT session available locally on your machine and requests:

```text
https://chatgpt.com/backend-api/wham/usage
```

The endpoint returns used percentages. This project converts them to remaining percentages:

```text
remaining_percent = 100 - used_percent
```

Important: this is an internal ChatGPT/Codex endpoint, not a public stable API. It works today because Codex itself uses this data shape, but OpenAI can change the endpoint or schema.

## Privacy

The app reads `~/.codex/auth.json` only to make the usage request.

It does not write your token, email, account id, or user id to the state file.

The local state file is:

```text
~/Library/Caches/com.easy-codex-limit-check/state.json
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
PYTHONPYCACHEPREFIX=/tmp/eclc-pycache python3 -m py_compile scripts/fetch_quota.py
```

## Repository Description

Use this for GitHub:

```text
macOS menu-bar widget for checking Codex Pro 5h and weekly rate-limit remaining percentages from your local Codex login.
```

Suggested topics:

```text
codex openai chatgpt macos menu-bar rate-limit quota launchagent
```

## License

MIT
