---
name: easy-codex-limit-status
description: Read and refresh the local Codex limit state file used by Easy Codex Limit Check.
---

# 5h / Week 额度查看

本技能用于触发额度拉取、查看当前状态文件内容，并给你下一步建议。

## 使用前提

- codex_wham 模式（默认）：本机 Codex 已登录，`~/.codex/auth.json` 中有有效 ChatGPT/Codex token。
- openai 模式：已设置环境变量 `OPENAI_API_KEY`，或将 Key 放入 Keychain：
  `security add-generic-password -a api_key -s com.easy-codex-limit-check.openai -w <key>`。
- 如果你使用组织账单：可选设置 `OPENAI_ORGANIZATION_ID`。
- manual 模式：不需要 API Key，只要在配置里写 `provider: manual` 和 `manual` 区域即可。
- 建议先执行一次 `./scripts/fetch_quota.py --dry-run`。

### 你当前是 codex_wham 场景（Pro 会员，无 API key）

```bash
cd easy-codex-limit-check
python3 ./scripts/fetch_quota.py \
  --provider codex_wham \
  --state-path "$HOME/Library/Caches/com.easy-codex-limit-check/state.json"
```

## 1) 手动刷新额度

```bash
cd easy-codex-limit-check
python3 ./scripts/fetch_quota.py \
  --config ./scripts/config.example.json \
  --state-path "$HOME/Library/Caches/com.easy-codex-limit-check/state.json"
```

## 2) 仅查看当前状态文件

```bash
cat "$HOME/Library/Caches/com.easy-codex-limit-check/state.json"
```

## 3) 结构说明（供菜单栏 App 使用）

输出会写入 `/Users/<你用户名>/Library/Caches/com.easy-codex-limit-check/state.json`，结构如下：

```json
{
  "rate_limits": [
    {
      "name": "Rate limits remaining",
      "five_h": { "remaining_percent": 73, "reset_at": "2026-04-24T19:05:30Z" },
      "week": { "remaining_percent": 95, "reset_at": "2026-04-29T03:06:20Z" }
    },
    {
      "name": "GPT-5.3-Codex-Spark",
      "five_h": { "remaining_percent": 89, "reset_at": "2026-04-24T20:09:32Z" },
      "week": { "remaining_percent": 94, "reset_at": "2026-04-28T08:48:13Z" }
    }
  ],
  "source": {
    "provider": "codex_wham",
    "api_base": "https://chatgpt.com/backend-api",
    "last_refresh_at": "2026-04-24T15:44:00Z",
    "refreshed": {...}
  },
  "window_version": 2
}
```

如果采集失败，`error` 会记录错误信息，且会保留最近一次可用数值。
