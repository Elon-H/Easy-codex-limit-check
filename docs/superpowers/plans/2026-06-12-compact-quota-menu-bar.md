# Compact Quota Menu Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current two-row segmented quota status item with a single-row double-capsule layout using continuous progress bars and compact reset text.

**Architecture:** Keep the existing Objective-C AppKit menu-bar app and state file contract. The change is isolated to status-item rendering in `menu-bar/Sources/QuotaMenuBarObjC/main.m`; quota fetching, approval watching, LaunchAgents, and clicked menu structure remain unchanged.

**Tech Stack:** Objective-C, AppKit `NSStatusItem`, custom `NSImage` drawing, existing shell build/install scripts.

---

## File Structure

- Modify `menu-bar/Sources/QuotaMenuBarObjC/main.m`
  - Replace the segmented two-row status-image renderer with compact single-row capsule rendering.
  - Add small drawing helpers for continuous bars, capsule backgrounds, and quota color interpolation.
  - Add a numeric date helper for weekly reset text (`M/d`).
  - Keep existing state parsing and menu construction intact.
- Keep `docs/superpowers/specs/2026-06-12-compact-quota-menu-bar-design.md`
  - Source of truth for visual requirements.
- No new app target, SwiftUI rewrite, data provider changes, or menu restructuring.

## Task 1: Add Compact Rendering Helpers

**Files:**
- Modify: `menu-bar/Sources/QuotaMenuBarObjC/main.m`

- [ ] **Step 1: Prepare helper names and remove the unused Chinese date path**

In `menu-bar/Sources/QuotaMenuBarObjC/main.m`, remove the `chineseDateFormatter` property:

```objc
@property(nonatomic, strong) NSDateFormatter *chineseDateFormatter;
```

Remove this initialization block from `-init`:

```objc
_chineseDateFormatter = [[NSDateFormatter alloc] init];
_chineseDateFormatter.dateFormat = @"M月d日";
_chineseDateFormatter.locale = [NSLocale localeWithLocaleIdentifier:@"zh_CN"];
```

Remove the current method:

```objc
- (NSString *)shortChineseDate:(NSString *)value {
    NSDate *date = [self dateFromString:value];
    return date ? [self.chineseDateFormatter stringFromDate:date] : @"--";
}
```

- [ ] **Step 2: Add numeric reset-date formatting**

Add this method where `shortDate:` and `detailTime:` are defined:

```objc
- (NSString *)shortNumericDate:(NSString *)value {
    NSDate *date = [self dateFromString:value];
    if (!date) {
        return @"--";
    }

    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.dateFormat = @"M/d";
    formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    return [formatter stringFromDate:date];
}
```

Expected behavior:
- `2026-06-18T03:22:46Z` renders as `6/18`.
- Invalid or missing dates render as `--`.

- [ ] **Step 3: Replace segmented-bar drawing with continuous-bar drawing helpers**

Delete the full `drawSegmentedBarInRect:percent:activeColor:dimmed:` method.

Add these helper methods after `clampedPercent:fallback:`:

```objc
- (NSColor *)colorBetween:(NSColor *)start end:(NSColor *)end amount:(double)amount {
    amount = MAX(0.0, MIN(1.0, amount));
    NSColor *a = [start colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
    NSColor *b = [end colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];

    CGFloat ar = 0.0, ag = 0.0, ab = 0.0, aa = 0.0;
    CGFloat br = 0.0, bg = 0.0, bb = 0.0, ba = 0.0;
    [a getRed:&ar green:&ag blue:&ab alpha:&aa];
    [b getRed:&br green:&bg blue:&bb alpha:&ba];

    return [NSColor colorWithCalibratedRed:ar + (br - ar) * amount
                                     green:ag + (bg - ag) * amount
                                      blue:ab + (bb - ab) * amount
                                     alpha:aa + (ba - aa) * amount];
}

- (NSColor *)quotaColorForRemainingPercent:(NSNumber *)value dimmed:(BOOL)dimmed {
    double percent = [self clampedPercent:value fallback:0.0];
    NSColor *green = [NSColor colorWithCalibratedRed:0.55 green:0.90 blue:0.20 alpha:1.0];
    NSColor *yellow = [NSColor colorWithCalibratedRed:0.95 green:0.78 blue:0.20 alpha:1.0];
    NSColor *orange = [NSColor colorWithCalibratedRed:1.00 green:0.48 blue:0.14 alpha:1.0];
    NSColor *red = [NSColor colorWithCalibratedRed:1.00 green:0.24 blue:0.23 alpha:1.0];

    NSColor *color = green;
    if (percent >= 70.0) {
        color = green;
    } else if (percent >= 40.0) {
        color = [self colorBetween:yellow end:green amount:(percent - 40.0) / 30.0];
    } else if (percent >= 20.0) {
        color = [self colorBetween:orange end:yellow amount:(percent - 20.0) / 20.0];
    } else {
        color = [self colorBetween:red end:orange amount:percent / 20.0];
    }

    return dimmed ? [color colorWithAlphaComponent:0.50] : color;
}

- (NSColor *)percentTextColorForRemainingPercent:(NSNumber *)value dimmed:(BOOL)dimmed pulseOn:(BOOL)pulseOn {
    if (pulseOn) {
        return [NSColor systemOrangeColor];
    }
    if (dimmed) {
        return [NSColor secondaryLabelColor];
    }
    double percent = [self clampedPercent:value fallback:100.0];
    if (percent < 40.0) {
        return [self quotaColorForRemainingPercent:value dimmed:NO];
    }
    return [NSColor labelColor];
}

- (void)drawProgressBarInRect:(NSRect)rect percent:(double)percent color:(NSColor *)color dimmed:(BOOL)dimmed {
    percent = MAX(0.0, MIN(100.0, percent));

    NSColor *trackColor = dimmed
        ? [NSColor colorWithCalibratedWhite:0.45 alpha:0.28]
        : [NSColor colorWithCalibratedWhite:0.18 alpha:0.30];
    NSBezierPath *track = [NSBezierPath bezierPathWithRoundedRect:rect xRadius:rect.size.height / 2.0 yRadius:rect.size.height / 2.0];
    [trackColor setFill];
    [track fill];

    CGFloat fillWidth = floor(rect.size.width * percent / 100.0);
    if (fillWidth <= 0.0) {
        return;
    }

    NSRect fillRect = NSMakeRect(rect.origin.x, rect.origin.y, fillWidth, rect.size.height);
    NSBezierPath *fill = [NSBezierPath bezierPathWithRoundedRect:fillRect xRadius:rect.size.height / 2.0 yRadius:rect.size.height / 2.0];
    [color setFill];
    [fill fill];
}
```

- [ ] **Step 4: Build to verify helper syntax**

Run:

```bash
menu-bar/scripts/build_objc_menu_bar.sh
```

Expected:
- Exit code `0`.
- Output ends with the built executable path:

```text
/Users/huangyilong/Documents/codex适配/easy-codex-limit-check/menu-bar/.build/release/QuotaMenuBar
```

- [ ] **Step 5: Commit helper changes**

Run:

```bash
git add menu-bar/Sources/QuotaMenuBarObjC/main.m
git commit -m "Add compact quota rendering helpers"
```

Expected:
- Commit succeeds.
- Only `menu-bar/Sources/QuotaMenuBarObjC/main.m` is included.

## Task 2: Replace The Status Item Image With Single-Row Capsules

**Files:**
- Modify: `menu-bar/Sources/QuotaMenuBarObjC/main.m`

- [ ] **Step 1: Add a capsule drawing helper**

Add this method after `drawProgressBarInRect:percent:color:dimmed:`:

```objc
- (void)drawQuotaCapsuleInRect:(NSRect)rect
                         label:(NSString *)label
                     remaining:(NSNumber *)remaining
                     resetText:(NSString *)resetText
                        dimmed:(BOOL)dimmed
                       pulseOn:(BOOL)pulseOn {
    NSColor *capsuleColor = dimmed
        ? [NSColor colorWithCalibratedWhite:0.32 alpha:0.22]
        : [NSColor colorWithCalibratedWhite:0.08 alpha:0.18];
    NSBezierPath *capsule = [NSBezierPath bezierPathWithRoundedRect:rect xRadius:rect.size.height / 2.0 yRadius:rect.size.height / 2.0];
    [capsuleColor setFill];
    [capsule fill];

    NSFont *labelFont = [NSFont systemFontOfSize:8.8 weight:NSFontWeightBold];
    NSFont *valueFont = [NSFont monospacedDigitSystemFontOfSize:9.0 weight:NSFontWeightSemibold];
    NSFont *resetFont = [NSFont monospacedDigitSystemFontOfSize:8.6 weight:NSFontWeightRegular];

    NSColor *labelColor = dimmed ? [NSColor secondaryLabelColor] : [NSColor labelColor];
    NSColor *mutedColor = dimmed ? [NSColor tertiaryLabelColor] : [NSColor secondaryLabelColor];
    NSColor *barColor = [self quotaColorForRemainingPercent:remaining dimmed:dimmed];
    NSColor *percentColor = [self percentTextColorForRemainingPercent:remaining dimmed:dimmed pulseOn:pulseOn];

    NSDictionary *labelAttrs = @{NSFontAttributeName: labelFont, NSForegroundColorAttributeName: labelColor};
    NSDictionary *valueAttrs = @{NSFontAttributeName: valueFont, NSForegroundColorAttributeName: percentColor};
    NSDictionary *resetAttrs = @{NSFontAttributeName: resetFont, NSForegroundColorAttributeName: mutedColor};

    NSString *percentText = [self percentString:remaining];
    CGFloat contentY = rect.origin.y + floor((rect.size.height - 9.0) / 2.0);
    CGFloat labelX = rect.origin.x + 7.0;
    CGFloat barX = labelX + (label.length > 2 ? 30.0 : 18.0);
    CGFloat barWidth = label.length > 2 ? 62.0 : 66.0;
    CGFloat pctX = barX + barWidth + 6.0;
    CGFloat resetX = pctX + 28.0;

    [label drawAtPoint:NSMakePoint(labelX, contentY) withAttributes:labelAttrs];
    [self drawProgressBarInRect:NSMakeRect(barX, rect.origin.y + floor((rect.size.height - 5.0) / 2.0), barWidth, 5.0)
                         percent:[self clampedPercent:remaining fallback:0.0]
                           color:barColor
                          dimmed:dimmed];
    [percentText drawAtPoint:NSMakePoint(pctX, contentY) withAttributes:valueAttrs];
    [resetText drawAtPoint:NSMakePoint(resetX, contentY) withAttributes:resetAttrs];
}
```

- [ ] **Step 2: Replace `statusImageWithState:stale:approvals:approvalState:fallbackTitle:`**

Replace the entire current `statusImageWithState:stale:approvals:approvalState:fallbackTitle:` method with:

```objc
- (NSImage *)statusImageWithState:(NSDictionary *)state
                            stale:(BOOL)stale
                        approvals:(NSArray *)approvals
                    approvalState:(NSDictionary *)approvalState
                    fallbackTitle:(NSString *)fallbackTitle {
    NSDictionary *primary = state ? [self primaryGroupFromState:state] : nil;
    NSDictionary *fiveH = DictionaryValue(primary[@"five_h"]) ?: DictionaryValue(state[@"five_h"]);
    NSDictionary *week = DictionaryValue(primary[@"week"]) ?: DictionaryValue(state[@"week"]);
    if (!fiveH && !week) {
        return nil;
    }

    NSNumber *fiveRemaining = [self remainingPercentForWindow:fiveH];
    NSNumber *weekRemaining = [self remainingPercentForWindow:week];
    NSString *fiveReset = [self shortTime:[self resetAtForWindow:fiveH]];
    NSString *weekReset = [self shortNumericDate:[self resetAtForWindow:week]];

    BOOL hasApprovals = approvals.count > 0;
    BOOL pulseEnabled = [self approvalPulseEnabled:approvalState];
    BOOL pulseOn = hasApprovals && pulseEnabled && self.approvalPulseOn;

    CGFloat height = MAX(NSStatusBar.systemStatusBar.thickness, 22.0);
    CGFloat approvalWidth = hasApprovals ? 46.0 : 0.0;
    CGFloat capsuleGap = 8.0;
    CGFloat fiveWidth = 134.0;
    CGFloat weekWidth = 148.0;
    CGFloat staleWidth = stale ? 10.0 : 0.0;
    CGFloat width = approvalWidth + fiveWidth + capsuleGap + weekWidth + staleWidth;

    NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(width, height)];
    image.template = NO;

    [image lockFocus];
    [[NSColor clearColor] setFill];
    NSRectFill(NSMakeRect(0, 0, width, height));

    CGFloat capsuleHeight = 18.0;
    CGFloat y = floor((height - capsuleHeight) / 2.0);
    CGFloat x = 0.0;

    if (hasApprovals) {
        NSColor *approvalColor = pulseOn ? [NSColor systemOrangeColor] : [NSColor labelColor];
        NSDictionary *approvalAttrs = @{
            NSFontAttributeName: [NSFont systemFontOfSize:8.8 weight:NSFontWeightBold],
            NSForegroundColorAttributeName: approvalColor
        };
        NSString *approvalText = [NSString stringWithFormat:@"审批 %lu", (unsigned long)approvals.count];
        [approvalText drawAtPoint:NSMakePoint(x + 2.0, y + 4.0) withAttributes:approvalAttrs];
        x += approvalWidth;
    }

    [self drawQuotaCapsuleInRect:NSMakeRect(x, y, fiveWidth, capsuleHeight)
                           label:@"5h"
                       remaining:fiveRemaining
                       resetText:fiveReset
                          dimmed:stale
                         pulseOn:pulseOn];
    x += fiveWidth + capsuleGap;

    [self drawQuotaCapsuleInRect:NSMakeRect(x, y, weekWidth, capsuleHeight)
                           label:@"Week"
                       remaining:weekRemaining
                       resetText:weekReset
                          dimmed:stale
                         pulseOn:NO];

    if (stale) {
        NSDictionary *staleAttrs = @{
            NSFontAttributeName: [NSFont systemFontOfSize:8.0 weight:NSFontWeightBold],
            NSForegroundColorAttributeName: [NSColor systemOrangeColor]
        };
        [@"!" drawAtPoint:NSMakePoint(width - 7.0, y + 4.0) withAttributes:staleAttrs];
    }

    [image unlockFocus];
    image.accessibilityDescription = fallbackTitle ?: @"Codex quota";
    return image;
}
```

Expected visual output:
- One row.
- No `Codex`.
- No Chinese `5小时` or `周限额`.
- No `剩余`.
- No `重置`.
- Two continuous bars instead of segmented bars.

- [ ] **Step 3: Build to catch Objective-C drawing regressions**

Run:

```bash
menu-bar/scripts/build_objc_menu_bar.sh
```

Expected:
- Exit code `0`.
- No selector, property, or undeclared identifier errors.

- [ ] **Step 4: Commit the new status image layout**

Run:

```bash
git add menu-bar/Sources/QuotaMenuBarObjC/main.m
git commit -m "Render compact quota status capsules"
```

Expected:
- Commit succeeds.
- Commit touches only `menu-bar/Sources/QuotaMenuBarObjC/main.m`.

## Task 3: Tighten Fallback Text And Approval/Stale Behavior

**Files:**
- Modify: `menu-bar/Sources/QuotaMenuBarObjC/main.m`

- [ ] **Step 1: Make fallback tooltip match the compact text rules**

Replace this line in `titleFromState:stale:`:

```objc
NSString *title = [NSString stringWithFormat:@"5h %@ %@ | W %@ %@", fiveText, fiveReset, weekText, weekReset];
```

with:

```objc
NSString *title = [NSString stringWithFormat:@"5h %@ %@ | Week %@ %@", fiveText, fiveReset, weekText, [self shortNumericDate:[self resetAtForWindow:week]]];
```

Expected:
- Tooltip remains useful when the status image is active.
- Weekly fallback uses `6/18` style instead of `Jun 18`.

- [ ] **Step 2: Keep fallback image failure behavior unchanged**

Do not change this behavior in `setStatusDisplayForState:stale:title:approvals:approvalState:`:

```objc
if (statusImage) {
    self.statusItem.length = statusImage.size.width + 8.0;
    self.statusItem.button.title = @"";
    self.statusItem.button.attributedTitle = [[NSAttributedString alloc] initWithString:@""];
    self.statusItem.button.image = statusImage;
    self.statusItem.button.imagePosition = NSImageOnly;
    self.statusItem.button.toolTip = title;
    return;
}
```

Expected:
- Existing image-button behavior remains.
- Text fallback still works if image rendering returns `nil`.

- [ ] **Step 3: Run syntax and build checks**

Run:

```bash
bash -n install.sh uninstall.sh menu-bar/scripts/*.sh
menu-bar/scripts/build_objc_menu_bar.sh
```

Expected:
- Both commands exit `0`.
- Build output points to `.build/release/QuotaMenuBar`.

- [ ] **Step 4: Commit fallback polish**

Run:

```bash
git add menu-bar/Sources/QuotaMenuBarObjC/main.m
git commit -m "Polish compact quota fallback text"
```

Expected:
- Commit succeeds if there was a diff.
- If Task 2 already made this exact fallback change, skip this commit and note that there is no diff.

## Task 4: Runtime Verification With Real And Low-Quota States

**Files:**
- Modify: none expected.
- Read: `/Users/huangyilong/Library/Caches/com.easy-codex-limit-check/state.json`
- Produce temporary screenshots under `/private/tmp/`.

- [ ] **Step 1: Reinstall and restart the LaunchAgents**

Run:

```bash
./install.sh
```

Expected:
- Exit code `0`.
- Output includes:

```text
Installed launch agents:
 - /Users/huangyilong/Library/LaunchAgents/com.easy-codex-limit-check.fetch.plist
 - /Users/huangyilong/Library/LaunchAgents/com.easy-codex-limit-check.approval-watcher.plist
 - /Users/huangyilong/Library/LaunchAgents/com.easy-codex-limit-check.menu-bar.plist
```

- [ ] **Step 2: Confirm menu-bar process is running**

Run:

```bash
pgrep -af QuotaMenuBar
/bin/launchctl print gui/501/com.easy-codex-limit-check.menu-bar
```

Expected:
- `pgrep` prints one running `QuotaMenuBar` app process.
- `launchctl` includes `state = running`.

- [ ] **Step 3: Capture the real menu-bar state**

Run:

```bash
screencapture -x -R 0,0,2560,90 /private/tmp/eclc-compact-menu-bar-real.png
```

Expected:
- Screenshot shows a one-row status item similar to:

```text
5h [bar] 70% 13:19   Week [bar] 78% 6/18
```

Manual check:
- No `Codex`.
- No `剩余`.
- No `重置`.
- No segmented cells.

- [ ] **Step 4: Verify low-quota colors without corrupting live state**

Copy the live state aside:

```bash
cp /Users/huangyilong/Library/Caches/com.easy-codex-limit-check/state.json /private/tmp/eclc-state-backup.json
```

Use a temporary Python one-liner to write low quota values:

```bash
python3 - <<'PY'
import json
from pathlib import Path
path = Path("/Users/huangyilong/Library/Caches/com.easy-codex-limit-check/state.json")
state = json.loads(path.read_text())
group = state["rate_limits"][0]
group["five_h"]["remaining_percent"] = 28
group["five_h"]["used_percent"] = 72
group["week"]["remaining_percent"] = 13
group["week"]["used_percent"] = 87
state["five_h"]["remaining"] = 28
state["five_h"]["used"] = 72
state["week"]["remaining"] = 13
state["week"]["used"] = 87
path.write_text(json.dumps(state, indent=2))
PY
```

Wait up to 35 seconds for the menu refresh, then capture:

```bash
screencapture -x -R 0,0,2560,90 /private/tmp/eclc-compact-menu-bar-low.png
```

Expected:
- `5h` bar and/or percent shifts toward orange.
- `Week` bar and/or percent shifts toward red.
- Text still fits in a single row.

Restore the live state:

```bash
cp /private/tmp/eclc-state-backup.json /Users/huangyilong/Library/Caches/com.easy-codex-limit-check/state.json
```

- [ ] **Step 5: Verify stale marker behavior**

Use a temporary Python one-liner to set `state_file_ttl_seconds` to `0`:

```bash
python3 - <<'PY'
import json
from pathlib import Path
path = Path("/Users/huangyilong/Library/Caches/com.easy-codex-limit-check/state.json")
state = json.loads(path.read_text())
state["state_file_ttl_seconds"] = 0
path.write_text(json.dumps(state, indent=2))
PY
```

Wait up to 35 seconds, then capture:

```bash
screencapture -x -R 0,0,2560,90 /private/tmp/eclc-compact-menu-bar-stale.png
```

Expected:
- A compact `!` appears.
- Bars/text dim.
- Values are not replaced with `0%`.

Restore the live state again:

```bash
cp /private/tmp/eclc-state-backup.json /Users/huangyilong/Library/Caches/com.easy-codex-limit-check/state.json
```

- [ ] **Step 6: Let the fetch agent refresh real state**

Run:

```bash
/Users/huangyilong/Library/Application\ Support/com.easy-codex-limit-check/scripts/run_fetch_quota.sh
```

Expected:
- Exit code `0`.
- `state.json` again shows real provider data with `source.provider` equal to `app_server` unless fallback was needed.

## Task 5: Final Checks And Push

**Files:**
- Modify: none expected.

- [ ] **Step 1: Run final verification commands**

Run:

```bash
bash -n install.sh uninstall.sh menu-bar/scripts/*.sh
menu-bar/scripts/build_objc_menu_bar.sh
git status --short --branch
```

Expected:
- Shell syntax command exits `0`.
- Build command exits `0`.
- Git status shows the feature branch and no uncommitted changes except intentional screenshot files under `/private/tmp`, which are outside the repo.

- [ ] **Step 2: Push the current branch**

Run:

```bash
git push origin codex/approval-watcher
```

Expected:
- Push succeeds.
- Remote branch contains the design spec, implementation plan, and compact status item implementation commits.

## Self-Review Notes

- Spec coverage:
  - Single-row double-capsule layout: Task 2.
  - Continuous bars instead of segmented cells: Task 1 and Task 2.
  - No `Codex`, no `剩余`, no `重置`: Task 2 and Task 4 screenshot checks.
  - `5h`, `Week`, `HH:mm`, `M/d`: Task 1, Task 2, Task 3.
  - Color changes as quota decreases: Task 1 and Task 4 low-quota fixture.
  - Approval pulse/marker: Task 2 keeps approval marker and pulse color.
  - Stale/error behavior: Task 2 keeps `!`; Task 4 verifies stale display; fallback remains in Task 3.
- Scope remains one status-item rendering change. Provider code, LaunchAgent shape, and clicked menu structure are not changed.
- No placeholders remain in this plan.
