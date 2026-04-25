# GitHub Upload Checklist

Repository:

```text
https://github.com/Elon-H/Easy-codex-limit-check
```

Recommended GitHub description:

```text
macOS menu-bar widget for checking Codex Pro 5h and weekly rate-limit remaining percentages from your local Codex login.
```

Recommended topics:

```text
codex, openai, chatgpt, macos, menu-bar, rate-limit, quota, launchagent
```

Suggested first release tag:

```text
v0.1.0
```

Before publishing:

1. Confirm `~/.codex/auth.json` is never committed.
2. Confirm no `state.json`, `.build/`, or logs are committed.
3. Run `./install.sh` locally once on a clean clone.
4. Confirm the README says App Server is primary and `/wham/usage` is a legacy fallback.
