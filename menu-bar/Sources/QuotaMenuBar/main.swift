import AppKit
import Foundation

struct QuotaValue: Codable {
    let limit: Double?
    let used: Double?
    let remaining: Double?
    let resetAt: String?
    let unit: String?
    let updatedAt: String?
    let label: String?

    enum CodingKeys: String, CodingKey {
        case limit
        case used
        case remaining
        case reset_at = "reset_at"
        case unit
        case updated_at = "updated_at"
        case label
    }
}

struct RateLimitWindow: Codable {
    let label: String?
    let usedPercent: Double?
    let remainingPercent: Double?
    let resetAt: String?
    let resetAfterSeconds: Int?
    let windowSeconds: Int?
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case label
        case usedPercent = "used_percent"
        case remainingPercent = "remaining_percent"
        case resetAt = "reset_at"
        case resetAfterSeconds = "reset_after_seconds"
        case windowSeconds = "window_seconds"
        case updatedAt = "updated_at"
    }
}

struct RateLimitGroup: Codable {
    let name: String?
    let meteredFeature: String?
    let allowed: Bool?
    let limitReached: Bool?
    let fiveH: RateLimitWindow?
    let week: RateLimitWindow?
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case name
        case meteredFeature = "metered_feature"
        case allowed
        case limitReached = "limit_reached"
        case fiveH = "five_h"
        case week
        case updatedAt = "updated_at"
    }
}

struct QuotaRefreshInfo: Codable {
    let fiveHUsedSource: String?
    let weekUsedSource: String?
    let fiveLimitUsd: Double?
    let weekLimitUsd: Double?
    let intervals: [String: String]?

    enum CodingKeys: String, CodingKey {
        case fiveHUsedSource = "five_h_used_source"
        case weekUsedSource = "week_used_source"
        case fiveLimitUsd = "five_limit_usd"
        case weekLimitUsd = "week_limit_usd"
        case intervals
    }
}

struct QuotaError: Codable {
    let message: String?
}

struct QuotaSource: Codable {
    let provider: String?
    let apiBase: String?
    let lastRefreshAt: String?
    let refreshed: QuotaRefreshInfo?

    enum CodingKeys: String, CodingKey {
        case provider
        case apiBase = "api_base"
        case lastRefreshAt = "last_refresh_at"
        case refreshed
    }
}

struct QuotaState: Codable {
    let fiveH: QuotaValue?
    let week: QuotaValue?
    let rateLimits: [RateLimitGroup]?
    let source: QuotaSource?
    let windowVersion: Int?
    let error: QuotaError?
    let lastRefreshAt: String?
    let staleAfterSeconds: Int?

    enum CodingKeys: String, CodingKey {
        case fiveH = "five_h"
        case week
        case rateLimits = "rate_limits"
        case source
        case windowVersion = "window_version"
        case error
        case lastRefreshAt = "last_refresh_at"
        case staleAfterSeconds = "state_file_ttl_seconds"
    }
}

@main
struct QuotaMenuBarApp {
    static func main() {
        let delegate = AppDelegate()
        let app = NSApplication.shared
        app.delegate = delegate
        app.run()
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var refreshTimer: Timer?
    private weak var titleMenuItem: NSMenuItem?
    private weak var detailMenuItem: NSMenuItem?
    private let dateFormatter = DateFormatter()
    private let dateOnlyFormatter = DateFormatter()
    private let detailDateFormatter = DateFormatter()
    private let statePath: URL
    private let defaultStateTTL = 180.0
    private var staleAfterSeconds: TimeInterval = 180.0
    private let decoder: JSONDecoder

    init() {
        let defaultState = NSString(
            string: "~/Library/Caches/com.easy-codex-limit-check/state.json"
        ).expandingTildeInPath
        let envState = ProcessInfo.processInfo.environment["CODEX_QUOTA_STATE_PATH"]
        let chosenPath = envState?.isEmpty == false ? envState! : defaultState

        self.statePath = URL(fileURLWithPath: chosenPath, isDirectory: false)
        self.decoder = JSONDecoder()
        super.init()

        dateFormatter.dateFormat = "HH:mm"
        dateFormatter.locale = Locale(identifier: "en_US_POSIX")
        dateOnlyFormatter.dateFormat = "MMM d"
        dateOnlyFormatter.locale = Locale(identifier: "en_US_POSIX")
        detailDateFormatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        detailDateFormatter.locale = Locale(identifier: "en_US_POSIX")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem?.button?.title = "quota..."
        statusItem?.button?.toolTip = "Easy Codex Limit Check"
        buildMenu()

        update()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: true) { [weak self] _ in
            self?.update()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        refreshTimer?.invalidate()
    }

    @objc private func refreshNow() {
        update()
    }

    @objc private func openPluginReadme() {
        let defaultPlugin = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("easy-codex-limit-check")

        let pluginRoot = ProcessInfo.processInfo.environment["CODEX_QUOTA_PLUGIN_PATH"]
        let path = pluginRoot.flatMap { URL(fileURLWithPath: $0) } ?? defaultPlugin
        let readme = path.appendingPathComponent("README.md")
        NSWorkspace.shared.open(readme)
    }

    @objc private func openStateFile() {
        NSWorkspace.shared.open(statePath)
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    private func buildMenu() {
        let menu = NSMenu(title: "Codex Quota")
        let titleItem = NSMenuItem(title: "Codex Quota", action: nil, keyEquivalent: "")
        titleItem.isEnabled = false
        self.titleMenuItem = titleItem
        menu.addItem(titleItem)

        menu.addItem(NSMenuItem.separator())

        let detailItem = NSMenuItem(title: "等待数据...")
        detailItem.isEnabled = false
        self.detailMenuItem = detailItem
        menu.addItem(detailItem)

        menu.addItem(NSMenuItem.separator())

        let refreshItem = NSMenuItem(title: "刷新状态", action: #selector(refreshNow), keyEquivalent: "r")
        refreshItem.target = self
        menu.addItem(refreshItem)
        menu.addItem(NSMenuItem.separator())
        let docsItem = NSMenuItem(title: "打开说明", action: #selector(openPluginReadme), keyEquivalent: "o")
        docsItem.target = self
        menu.addItem(docsItem)
        let stateItem = NSMenuItem(title: "打开状态文件", action: #selector(openStateFile), keyEquivalent: "s")
        stateItem.target = self
        menu.addItem(stateItem)
        menu.addItem(NSMenuItem.separator())
        let quitItem = NSMenuItem(title: "退出", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem?.menu = menu
    }

    private func formatValue(_ value: Double?, unit: String? = nil) -> String {
        guard let value else { return "--" }
        if value < 0 { return "--" }
        if unit == "%" {
            return String(format: "%.0f%%", value)
        }
        if value == floor(value) {
            return String(format: "%.0f", value)
        }
        if value >= 1000 {
            return String(format: "%.0f", value)
        }
        return String(format: "%.2f", value)
    }

    private func formatPercent(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(format: "%.0f%%", value)
    }

    private func displayUnit(_ value: String?) -> String {
        let normalized = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if normalized.isEmpty {
            return "USD"
        }
        return normalized
    }

    private func parseDate(_ value: String?) -> Date? {
        guard let value else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = f.date(from: value) {
            return date
        }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: value)
    }

    private func formatReset(_ date: Date?) -> String {
        guard let date else { return "--" }
        return dateFormatter.string(from: date)
    }

    private func formatResetDate(_ date: Date?) -> String {
        guard let date else { return "--" }
        return dateOnlyFormatter.string(from: date)
    }

    private func formatUpdated(_ date: Date?) -> String {
        guard let date else { return "--" }
        return detailDateFormatter.string(from: date)
    }

    private func buildLabelLine(label: String, value: QuotaValue?, resetAsDate: Bool = false) -> String {
        guard let value else { return "\(label): 未配置" }
        let remaining = formatValue(value.remaining, unit: value.unit)
        let limit = formatValue(value.limit, unit: value.unit)
        let unitText = displayUnit(value.unit)
        let resetAtDate = parseDate(value.resetAt)
        let resetAt = resetAsDate ? formatResetDate(resetAtDate) : formatReset(resetAtDate)
        if let used = value.used {
            return "\(label): 剩余 \(remaining)/\(limit) \(unitText)（已用 \(formatValue(used, unit: value.unit))，重置 \(resetAt)）"
        }
        return "\(label): \(remaining)/\(limit) \(unitText)（重置 \(resetAt)）"
    }

    private func buildRateLimitLine(label: String, value: RateLimitWindow?, resetAsDate: Bool = false) -> String {
        guard let value else { return "\(label): --" }
        let resetAtDate = parseDate(value.resetAt)
        let resetAt = resetAsDate ? formatResetDate(resetAtDate) : formatReset(resetAtDate)
        return "\(label): \(formatPercent(value.remainingPercent))（重置 \(resetAt)）"
    }

    private func buildRateLimitSummary(_ groups: [RateLimitGroup]) -> (String, String, String?) {
        let first = groups.first
        let firstFive = first?.fiveH
        let firstWeek = first?.week
        let title = "5h \(formatPercent(firstFive?.remainingPercent)) \(formatReset(parseDate(firstFive?.resetAt))) | W \(formatPercent(firstWeek?.remainingPercent)) \(formatResetDate(parseDate(firstWeek?.resetAt)))"

        let lines = groups.flatMap { group -> [String] in
            let name = group.name ?? "Rate limits remaining"
            return [
                name,
                "  \(buildRateLimitLine(label: "5h", value: group.fiveH))",
                "  \(buildRateLimitLine(label: "Weekly", value: group.week, resetAsDate: true))",
            ]
        }
        let latest = groups.compactMap { parseDate($0.updatedAt) }.max().map(formatUpdated)
        return (title, lines.joined(separator: "\n"), latest)
    }

    private func isStateStale(_ updatedAt: String?) -> Bool {
        guard let updatedAt, let updatedDate = parseDate(updatedAt) else { return false }
        return Date().timeIntervalSince(updatedDate) > staleAfterSeconds
    }

    private func update() {
        guard let data = try? Data(contentsOf: statePath) else {
            updateMenuState(
                title: "quota: unavailable",
                subtitle: "状态文件未生成"
            )
            return
        }

        do {
            let state = try decoder.decode(QuotaState.self, from: data)
            staleAfterSeconds = TimeInterval(state.staleAfterSeconds ?? Int(defaultStateTTL))
            if let rateLimits = state.rateLimits, !rateLimits.isEmpty {
                let summary = buildRateLimitSummary(rateLimits)
                let latestLine = summary.2.map { "\n最新更新: \($0)" } ?? ""
                updateMenuState(title: summary.0, subtitle: summary.1 + latestLine)
                if let error = state.error?.message, !error.isEmpty {
                    updateMenuState(title: summary.0, subtitle: summary.1 + latestLine + "\n错误: \(error)")
                }
                return
            }
            guard let five = state.fiveH, let week = state.week else {
                updateMenuState(
                    title: "quota: invalid",
                    subtitle: "文件字段缺失"
                )
                return
            }

            let stale = isStateStale(five.updatedAt ?? week.updatedAt)
            let fiveUnit = displayUnit(five.unit)
            let weekUnit = displayUnit(week.unit)
            let fiveShort = "\(formatValue(five.remaining))/\(formatValue(five.limit)) \(fiveUnit)"
            let weekShort = "\(formatValue(week.remaining))/\(formatValue(week.limit)) \(weekUnit)"
            let fiveReset = formatReset(parseDate(five.resetAt))
            let weekReset = formatResetDate(parseDate(week.resetAt))
            let suffix = stale ? "（旧）" : ""
            let title = "5h \(fiveShort) \(fiveReset) | W \(weekShort) \(weekReset) \(suffix)"
            let lastUpdatedAt = parseDate(state.source?.lastRefreshAt) ?? parseDate(five.updatedAt) ?? parseDate(week.updatedAt)
            let subtitle = "\(buildLabelLine(label: "5h", value: five))\n" +
                "\(buildLabelLine(label: "W", value: week, resetAsDate: true))\n" +
                "最新更新: \(formatUpdated(lastUpdatedAt))"

            updateMenuState(title: title, subtitle: subtitle)

            if let error = state.error?.message, !error.isEmpty {
                updateMenuState(
                    title: title,
                    subtitle: subtitle + "\n错误: \(error)"
                )
            }
        } catch {
            updateMenuState(
                title: "quota: parse-error",
                subtitle: error.localizedDescription
            )
        }
    }

    private func updateMenuState(title: String, subtitle: String) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.statusItem?.button?.title = title
            self.titleMenuItem?.title = title
            self.detailMenuItem?.title = "详情: \(subtitle)"
        }
    }
}
