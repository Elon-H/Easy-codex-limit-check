# Menu Bar App

本目录构建一个原生 macOS 菜单栏程序 `QuotaMenuBar`，读取并展示：

- 主 Codex 额度的 `5h / Weekly` 剩余百分比与重置时间
- 附加模型额度（如 `GPT-5.3-Codex-Spark`）的 `5h / Weekly` 剩余百分比与重置时间

## 本地运行

```bash
cd easy-codex-limit-check/menu-bar
scripts/build_objc_menu_bar.sh
scripts/run_menu_bar.sh
```

## 常用环境变量

- `CODEX_QUOTA_STATE_PATH`：状态文件路径（默认 `~/Library/Caches/com.easy-codex-limit-check/state.json`）
- `CODEX_QUOTA_PLUGIN_PATH`：用于“打开说明”链接定位的插件根路径（默认会自动拼接常见路径）
- `CODEX_QUOTA_MENU_BAR_BIN`：可在启动脚本里覆盖菜单栏二进制路径

## 说明

启动脚本 `scripts/run_menu_bar.sh` 会先尝试 `menu-bar/.build/release/QuotaMenuBar`，若不存在会用 Objective-C/AppKit 入口自动构建；这可以避开本机 Swift SDK/CommandLineTools 小版本不匹配导致的 `swift build` 失败。

安装脚本会把运行时副本放到 `~/Library/Application Support/com.easy-codex-limit-check/`，LaunchAgent 从那里启动，避免 macOS 对 `~/Documents` 后台访问的 TCC 限制。

### 运行前准备

- 默认 `codex_wham` 模式需要本机 Codex 已登录，并且 `~/.codex/auth.json` 中有有效 token。
- 默认 `codex_wham` 模式不需要 OpenAI API key；它读取本机 Codex 登录态并写入本地状态文件。
- 如果你是 manual 模式，请在配置里将 `provider` 改为 `manual`，并在 `manual` 区域写入额度；启动脚本本身无需钥匙。

### 启动项脚本

```bash
cd easy-codex-limit-check/menu-bar
chmod +x scripts/*.sh
./scripts/install-launch-agents.sh
```
