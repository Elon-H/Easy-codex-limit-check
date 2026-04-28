---
name: codex-quota-menu-bar
description: Install, run, and auto-start the macOS menu bar quota widget.
---

# 安装状态栏显示端

本技能用于把 `menu-bar/` 下的菜单栏 App、`scripts/fetch_quota.py` 和 `scripts/watch_approvals.py` 串起来。

## 步骤 A：配置并安装 LaunchAgent（抓数+刷新）

```bash
cd easy-codex-limit-check/menu-bar
chmod +x scripts/install-launch-agents.sh scripts/run_fetch_quota.sh
./scripts/install-launch-agents.sh
```

脚本会做四件事：

1. 创建状态文件目录 `~/Library/Caches/com.easy-codex-limit-check/`
2. 生成并加载 `com.easy-codex-limit-check.fetch`（每分钟跑一次抓数）
3. 生成并加载 `com.easy-codex-limit-check.approval-watcher`（监听 Codex awaiting approval）
4. 生成并加载 `com.easy-codex-limit-check.menu-bar`（开机启动菜单栏 App）

> 默认 `app_server` 模式不需要 API key，但需要本机 Codex 已登录并能运行 `codex app-server --listen stdio://`。
> approval watcher 使用同一个本地 app-server stdio 入口，不会自动批准请求。
>
> openai 模式支持两种秘钥方式：
> - `OPENAI_API_KEY`（以及可选 `OPENAI_ORGANIZATION_ID`）
> - macOS Keychain：`security add-generic-password -a api_key -s com.easy-codex-limit-check.openai -w <key>`
>
> 注意：manual 模式不需要任何 API key，只要配置好 `provider: manual` 和 `manual` 区域数据即可。

> 启动脚本会把 `CODEX_QUOTA_STATE_PATH` 等运行时环境变量写入 `LaunchAgent`，避免登录 shell 丢失的环境问题。

## 步骤 B：临时运行（用于调试）

```bash
cd easy-codex-limit-check/menu-bar
scripts/build_objc_menu_bar.sh
scripts/run_menu_bar.sh
```

## 步骤 C：卸载

```bash
cd easy-codex-limit-check/menu-bar
./scripts/uninstall-launch-agents.sh
```
