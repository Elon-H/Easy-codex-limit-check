# Compact Quota Menu Bar Design

## Status

Approved visual direction: B v2, single-row double capsules with continuous progress bars.

This spec covers the menu-bar status item only. It does not change quota fetching, approval detection, LaunchAgents, or the clicked menu details.

## Goals

- Make the status item calmer and less crowded than the current two-row layout.
- Keep both primary windows visible in the menu bar: `5h` and `Week`.
- Remove redundant words so the item reads like native macOS status information.
- Make low quota visually obvious through color, without adding warning text.

## Status Bar Layout

Use one horizontal row containing two compact capsules:

```text
5h   [continuous bar]  70%  13:19    Week [continuous bar]  78%  6/18
```

Text rules:

- Do not show `Codex` in the status item.
- Use `5h`, not `5小时`.
- Use `Week`, not `周限额`.
- Show the remaining percent as `70%`, not `剩余 70%`.
- Show the 5h reset as local `HH:mm`, for example `13:19`.
- Show the weekly reset as `M/d`, for example `6/18`.
- Do not append `重置`.

Each capsule contains:

- short label
- continuous rounded progress bar
- remaining percentage
- reset time/date

## Progress Bar Behavior

The bar fill represents remaining quota, not used quota.

- `remaining_percent = 100 - used_percent` when only used percent is available.
- Clamp rendered percentage to `0...100`.
- Unknown values should render as empty/neutral, while the tooltip and menu keep exposing the fallback text.

Color should interpolate by remaining quota:

- `>= 70%`: green
- `40%...70%`: green to yellow-green
- `20%...40%`: yellow-orange to orange
- `< 20%`: orange to red

The percent text may use the same color family as the bar when quota is low. Normal/high quota should keep text in the standard menu-bar label color so the item does not look noisy.

## Width And Density

The target status item should be roughly `245...285 px` wide in the normal two-window state.

The implementation should avoid two visual rows in the menu bar. If the content does not fit at the current menu-bar size, reduce bar width before reducing font size. Font size should remain readable on a Retina Mac display.

Recommended starting geometry:

- item height: system status-bar thickness
- capsule height: `17...19 px`
- capsule padding: `6...8 px`
- bar width: `56...72 px`
- bar height: `4...6 px`
- gap between capsules: `7...9 px`

## Approval State

Pending approvals still need to override the quiet quota presentation enough to be noticed.

Recommended behavior:

- Keep the same single-row capsule structure when possible.
- Add a short leading approval marker such as `审批 1` or `APPROVAL 1`.
- Pulse the approval marker or percent text with the existing orange pulse behavior.
- Do not remove quota information unless space is insufficient.

If space is insufficient with approvals active, prefer:

```text
审批 1  5h 70% 13:19 | W 78%
```

The clicked menu remains the place for full approval details and actions.

## Stale Or Error State

For stale quota data:

- Prefix or suffix the item with a compact `!`.
- Dim the progress bars and text.
- Keep the last valid quota values visible.

For unreadable state or missing quota windows:

- Fall back to the existing text title behavior.
- Do not show `0%` unless the source explicitly reports zero remaining quota.

## Clicked Menu

The clicked menu can stay structurally unchanged for this design pass.

Later polish can make the menu details match the same compact labels, but that is out of scope for the status item implementation.

## Testing

Implementation should be verified with:

- ObjC menu-bar build script.
- Shell syntax checks for install and menu-bar scripts.
- Runtime restart through `install.sh`.
- A top-menu screenshot showing the single-row double-capsule status item.
- State fixtures or temporary state edits for high, medium, low, and stale quota cases.

## Non-Goals

- No changes to App Server quota provider behavior.
- No changes to `/wham/usage` fallback behavior.
- No new SwiftUI rewrite.
- No desktop widget or separate window.
- No extra model buckets in the status item; additional buckets remain in the clicked menu.
