#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>

static NSString *StringValue(id value) {
    return [value isKindOfClass:[NSString class]] ? value : nil;
}

static NSNumber *NumberValue(id value) {
    return [value isKindOfClass:[NSNumber class]] ? value : nil;
}

static NSDictionary *DictionaryValue(id value) {
    return [value isKindOfClass:[NSDictionary class]] ? value : nil;
}

static NSArray *ArrayValue(id value) {
    return [value isKindOfClass:[NSArray class]] ? value : nil;
}

static NSString *EnvironmentValue(NSString *key) {
    NSString *value = [NSProcessInfo processInfo].environment[key];
    return value.length > 0 ? value : nil;
}

static const CGFloat QuotaHorizontalPadding = 5.0;
static const CGFloat QuotaInlineGap = 4.0;
static const CGFloat QuotaBarWidth = 38.0;
static const CGFloat QuotaMinBarWidth = 32.0;
static const CGFloat QuotaBarHeight = 14.0;
static const CGFloat QuotaBarYOffset = 1.0;

@interface AppDelegate : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSStatusItem *statusItem;
@property(nonatomic, strong) NSTimer *refreshTimer;
@property(nonatomic, strong) NSTimer *pulseTimer;
@property(nonatomic, strong) NSURL *stateURL;
@property(nonatomic, strong) NSURL *approvalStateURL;
@property(nonatomic, strong) NSURL *approvalDecisionsURL;
@property(nonatomic, strong) NSDateFormatter *timeFormatter;
@property(nonatomic, strong) NSDateFormatter *dateOnlyFormatter;
@property(nonatomic, strong) NSDateFormatter *detailDateFormatter;
@property(nonatomic, strong) NSISO8601DateFormatter *isoFormatter;
@property(nonatomic, strong) NSMutableSet<NSString *> *notifiedApprovalIds;
@property(nonatomic, copy) NSString *pluginRoot;
@property(nonatomic, copy) NSString *fetchScript;
@property(nonatomic, assign) BOOL approvalPulseOn;
@end

@implementation AppDelegate

- (instancetype)init {
    self = [super init];
    if (!self) {
        return nil;
    }

    NSString *statePath = EnvironmentValue(@"CODEX_QUOTA_STATE_PATH");
    if (!statePath) {
        statePath = [@"~/Library/Caches/com.easy-codex-limit-check/state.json" stringByExpandingTildeInPath];
    }
    _stateURL = [NSURL fileURLWithPath:statePath isDirectory:NO];

    NSString *approvalStatePath = EnvironmentValue(@"CODEX_APPROVAL_STATE_PATH");
    if (!approvalStatePath) {
        approvalStatePath = [@"~/Library/Caches/com.easy-codex-limit-check/approval_state.json" stringByExpandingTildeInPath];
    }
    _approvalStateURL = [NSURL fileURLWithPath:approvalStatePath isDirectory:NO];

    NSString *approvalDecisionsPath = EnvironmentValue(@"CODEX_APPROVAL_DECISIONS_PATH");
    if (!approvalDecisionsPath) {
        approvalDecisionsPath = [@"~/Library/Caches/com.easy-codex-limit-check/approval_decisions.jsonl" stringByExpandingTildeInPath];
    }
    _approvalDecisionsURL = [NSURL fileURLWithPath:approvalDecisionsPath isDirectory:NO];

    NSString *pluginPath = EnvironmentValue(@"CODEX_QUOTA_PLUGIN_PATH");
    if (!pluginPath) {
        pluginPath = [NSHomeDirectory() stringByAppendingPathComponent:@"easy-codex-limit-check"];
    }
    _pluginRoot = [pluginPath copy];

    NSString *fetchScript = EnvironmentValue(@"CODEX_QUOTA_FETCH_SCRIPT");
    if (!fetchScript) {
        fetchScript = [_pluginRoot stringByAppendingPathComponent:@"menu-bar/scripts/run_fetch_quota.sh"];
    }
    _fetchScript = [fetchScript copy];

    _timeFormatter = [[NSDateFormatter alloc] init];
    _timeFormatter.dateFormat = @"HH:mm";
    _timeFormatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];

    _dateOnlyFormatter = [[NSDateFormatter alloc] init];
    _dateOnlyFormatter.dateFormat = @"MMM d";
    _dateOnlyFormatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];

    _detailDateFormatter = [[NSDateFormatter alloc] init];
    _detailDateFormatter.dateFormat = @"yyyy-MM-dd HH:mm:ss";
    _detailDateFormatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];

    _isoFormatter = [[NSISO8601DateFormatter alloc] init];
    _isoFormatter.formatOptions = NSISO8601DateFormatWithInternetDateTime;

    _notifiedApprovalIds = [NSMutableSet set];
    _approvalPulseOn = NO;

    return self;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    self.statusItem = [NSStatusBar.systemStatusBar statusItemWithLength:NSVariableStatusItemLength];
    self.statusItem.button.title = @"quota...";
    self.statusItem.button.toolTip = @"Easy Codex Limit Check";

    [self updateMenu];
    self.refreshTimer = [NSTimer scheduledTimerWithTimeInterval:30.0
                                                        target:self
                                                      selector:@selector(updateMenu)
                                                      userInfo:nil
                                                       repeats:YES];
}

- (void)applicationWillTerminate:(NSNotification *)notification {
    (void)notification;
    [self.refreshTimer invalidate];
    [self.pulseTimer invalidate];
}

- (NSDate *)dateFromString:(NSString *)value {
    if (value.length == 0) {
        return nil;
    }

    NSDate *date = [self.isoFormatter dateFromString:value];
    if (date) {
        return date;
    }

    NSArray *formats = @[
        @"yyyy-MM-dd'T'HH:mm:ss'Z'",
        @"yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",
        @"yyyy-MM-dd HH:mm:ss"
    ];
    NSDateFormatter *fallback = [[NSDateFormatter alloc] init];
    fallback.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    fallback.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
    for (NSString *format in formats) {
        fallback.dateFormat = format;
        date = [fallback dateFromString:value];
        if (date) {
            return date;
        }
    }
    return nil;
}

- (NSString *)shortTime:(NSString *)value {
    NSDate *date = [self dateFromString:value];
    return date ? [self.timeFormatter stringFromDate:date] : @"--:--";
}

- (NSString *)shortDate:(NSString *)value {
    NSDate *date = [self dateFromString:value];
    return date ? [self.dateOnlyFormatter stringFromDate:date] : @"--";
}

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

- (NSString *)detailTime:(NSString *)value {
    NSDate *date = [self dateFromString:value];
    return date ? [self.detailDateFormatter stringFromDate:date] : @"--";
}

- (NSString *)percentString:(NSNumber *)value {
    if (!value) {
        return @"--";
    }
    return [NSString stringWithFormat:@"%.0f%%", [self clampedPercent:value fallback:0.0]];
}

- (NSNumber *)remainingPercentForWindow:(NSDictionary *)window {
    NSNumber *remaining = NumberValue(window[@"remaining_percent"]);
    if (remaining) {
        return remaining;
    }

    NSNumber *legacyRemaining = NumberValue(window[@"remaining"]);
    if (legacyRemaining) {
        return legacyRemaining;
    }

    NSNumber *used = NumberValue(window[@"used_percent"]);
    if (used) {
        double value = 100.0 - used.doubleValue;
        if (value < 0.0) {
            value = 0.0;
        }
        if (value > 100.0) {
            value = 100.0;
        }
        return @(value);
    }

    return nil;
}

- (NSString *)resetAtForWindow:(NSDictionary *)window {
    return StringValue(window[@"reset_at"]);
}

- (NSDictionary *)primaryGroupFromState:(NSDictionary *)state {
    NSArray *groups = ArrayValue(state[@"rate_limits"]);
    if (groups.count > 0) {
        return DictionaryValue(groups.firstObject);
    }
    return nil;
}

- (NSString *)titleFromState:(NSDictionary *)state stale:(BOOL)stale {
    NSDictionary *primary = [self primaryGroupFromState:state];
    NSDictionary *fiveH = DictionaryValue(primary[@"five_h"]) ?: DictionaryValue(state[@"five_h"]);
    NSDictionary *week = DictionaryValue(primary[@"week"]) ?: DictionaryValue(state[@"week"]);

    NSString *fiveText = [self percentString:[self remainingPercentForWindow:fiveH]];
    NSString *weekText = [self percentString:[self remainingPercentForWindow:week]];
    NSString *fiveReset = [self shortTime:[self resetAtForWindow:fiveH]];

    if (!fiveH && !week) {
        return stale ? @"quota stale" : @"quota --";
    }

    NSString *title = [NSString stringWithFormat:@"5h %@ %@ | Week %@ %@", fiveText, fiveReset, weekText, [self shortNumericDate:[self resetAtForWindow:week]]];
    return stale ? [@"! " stringByAppendingString:title] : title;
}

- (double)clampedPercent:(NSNumber *)value fallback:(double)fallback {
    if (!value) {
        return fallback;
    }
    double percent = value.doubleValue;
    if (percent < 0.0) {
        return 0.0;
    }
    if (percent > 100.0) {
        return 100.0;
    }
    return percent;
}

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

- (void)drawQuotaBarInRect:(NSRect)rect percent:(double)percent color:(NSColor *)color text:(NSString *)text dimmed:(BOOL)dimmed {
    percent = MAX(0.0, MIN(100.0, percent));

    NSColor *trackColor = dimmed
        ? [NSColor colorWithCalibratedWhite:0.42 alpha:0.38]
        : [NSColor colorWithCalibratedWhite:0.12 alpha:0.55];
    NSColor *fillColor = dimmed ? [color colorWithAlphaComponent:0.55] : color;

    NSBezierPath *track = [NSBezierPath bezierPathWithRoundedRect:rect xRadius:rect.size.height / 2.0 yRadius:rect.size.height / 2.0];
    [trackColor setFill];
    [track fill];

    [NSGraphicsContext saveGraphicsState];
    [track addClip];
    CGFloat fillWidth = floor(rect.size.width * percent / 100.0);
    if (fillWidth > 0.0) {
        NSRect fillRect = NSMakeRect(rect.origin.x, rect.origin.y, fillWidth, rect.size.height);
        [fillColor setFill];
        NSRectFill(fillRect);
    }
    [NSGraphicsContext restoreGraphicsState];

    NSFont *textFont = [NSFont monospacedDigitSystemFontOfSize:10.2 weight:NSFontWeightHeavy];
    NSColor *textColor = dimmed ? [NSColor secondaryLabelColor] : (percent >= 52.0 ? [NSColor blackColor] : [NSColor whiteColor]);
    NSDictionary *textAttrs = @{NSFontAttributeName: textFont, NSForegroundColorAttributeName: textColor};
    NSSize textSize = [text sizeWithAttributes:textAttrs];
    CGFloat textX = rect.origin.x + floor((rect.size.width - textSize.width) / 2.0);
    CGFloat textY = rect.origin.y + floor((rect.size.height - textSize.height) / 2.0) - 0.5;
    [text drawAtPoint:NSMakePoint(textX, textY) withAttributes:textAttrs];
}

- (NSFont *)quotaLabelFont {
    return [NSFont systemFontOfSize:9.8 weight:NSFontWeightBold];
}

- (NSFont *)quotaResetFont {
    return [NSFont monospacedDigitSystemFontOfSize:10.4 weight:NSFontWeightSemibold];
}

- (CGFloat)quotaCapsuleWidthForLabel:(NSString *)label resetText:(NSString *)resetText {
    NSDictionary *labelAttrs = @{NSFontAttributeName: [self quotaLabelFont]};
    NSDictionary *resetAttrs = @{NSFontAttributeName: [self quotaResetFont]};
    CGFloat labelWidth = ceil([label sizeWithAttributes:labelAttrs].width);
    CGFloat resetWidth = ceil([resetText sizeWithAttributes:resetAttrs].width);
    return ceil(QuotaHorizontalPadding
                + labelWidth
                + QuotaInlineGap
                + QuotaBarWidth
                + QuotaInlineGap
                + resetWidth
                + QuotaHorizontalPadding);
}

- (void)drawQuotaCapsuleInRect:(NSRect)rect
                         label:(NSString *)label
                     remaining:(NSNumber *)remaining
                     resetText:(NSString *)resetText
                        dimmed:(BOOL)dimmed
                       pulseOn:(BOOL)pulseOn {
    NSFont *labelFont = [self quotaLabelFont];
    NSFont *resetFont = [self quotaResetFont];

    NSColor *labelColor = dimmed ? [NSColor secondaryLabelColor] : [NSColor labelColor];
    NSColor *resetColor = dimmed ? [NSColor secondaryLabelColor] : [NSColor labelColor];
    NSColor *barColor = [self quotaColorForRemainingPercent:remaining dimmed:dimmed];
    if (pulseOn) {
        barColor = [NSColor systemOrangeColor];
    }

    NSDictionary *labelAttrs = @{NSFontAttributeName: labelFont, NSForegroundColorAttributeName: labelColor};
    NSDictionary *resetAttrs = @{NSFontAttributeName: resetFont, NSForegroundColorAttributeName: resetColor};

    double percent = [self clampedPercent:remaining fallback:0.0];
    NSString *percentText = remaining ? [NSString stringWithFormat:@"%.0f%%", percent] : @"--";
    CGFloat labelX = rect.origin.x + QuotaHorizontalPadding;
    CGFloat labelWidth = ceil([label sizeWithAttributes:labelAttrs].width);
    CGFloat resetWidth = ceil([resetText sizeWithAttributes:resetAttrs].width);
    CGFloat resetX = NSMaxX(rect) - QuotaHorizontalPadding - resetWidth;
    CGFloat barX = labelX + labelWidth + QuotaInlineGap;
    CGFloat availableBarWidth = floor(resetX - QuotaInlineGap - barX);
    CGFloat barWidth = MIN(QuotaBarWidth, availableBarWidth);
    if (barWidth < QuotaMinBarWidth) {
        barWidth = MAX(0.0, availableBarWidth);
    }

    NSSize labelSize = [label sizeWithAttributes:labelAttrs];
    NSSize resetSize = [resetText sizeWithAttributes:resetAttrs];
    CGFloat labelY = rect.origin.y + floor((rect.size.height - labelSize.height) / 2.0);
    CGFloat resetY = rect.origin.y + floor((rect.size.height - resetSize.height) / 2.0);

    [label drawAtPoint:NSMakePoint(labelX, labelY) withAttributes:labelAttrs];
    if (barWidth > 0.0) {
        [self drawQuotaBarInRect:NSMakeRect(barX, rect.origin.y + floor((rect.size.height - QuotaBarHeight) / 2.0) + QuotaBarYOffset, barWidth, QuotaBarHeight)
                          percent:percent
                            color:barColor
                             text:percentText
                           dimmed:dimmed];
    }
    [resetText drawAtPoint:NSMakePoint(resetX, resetY) withAttributes:resetAttrs];
}

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
    NSFont *approvalFont = [NSFont systemFontOfSize:8.8 weight:NSFontWeightBold];
    NSColor *approvalColor = pulseOn ? [NSColor systemOrangeColor] : [NSColor labelColor];
    NSDictionary *approvalAttrs = @{
        NSFontAttributeName: approvalFont,
        NSForegroundColorAttributeName: approvalColor
    };
    NSString *approvalText = nil;
    if (hasApprovals) {
        NSString *approvalCountText = approvals.count > 99
            ? @"99+"
            : [NSString stringWithFormat:@"%lu", (unsigned long)approvals.count];
        approvalText = [NSString stringWithFormat:@"审批 %@", approvalCountText];
    }

    CGFloat height = MAX(NSStatusBar.systemStatusBar.thickness, 22.0);
    CGFloat approvalWidth = hasApprovals ? ceil([approvalText sizeWithAttributes:approvalAttrs].width) + 8.0 : 0.0;
    CGFloat capsuleGap = 5.0;
    CGFloat fiveWidth = [self quotaCapsuleWidthForLabel:@"5h" resetText:fiveReset];
    CGFloat weekWidth = [self quotaCapsuleWidthForLabel:@"Week" resetText:weekReset];
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

- (NSDictionary *)loadJSONFromURL:(NSURL *)url error:(NSError **)error {
    NSData *data = [NSData dataWithContentsOfURL:url options:0 error:error];
    if (!data) {
        return nil;
    }

    id json = [NSJSONSerialization JSONObjectWithData:data options:0 error:error];
    return DictionaryValue(json);
}

- (NSDictionary *)loadState:(NSError **)error {
    return [self loadJSONFromURL:self.stateURL error:error];
}

- (NSDictionary *)loadApprovalState:(NSError **)error {
    return [self loadJSONFromURL:self.approvalStateURL error:error];
}

- (NSDate *)lastRefreshDateFromState:(NSDictionary *)state {
    NSString *sourceRefresh = StringValue(DictionaryValue(state[@"source"])[@"last_refresh_at"]);
    NSDate *date = [self dateFromString:sourceRefresh];
    if (date) {
        return date;
    }

    NSString *stateRefresh = StringValue(state[@"last_refresh_at"]);
    date = [self dateFromString:stateRefresh];
    if (date) {
        return date;
    }

    NSDictionary *primary = [self primaryGroupFromState:state];
    NSString *groupRefresh = StringValue(primary[@"updated_at"]);
    return [self dateFromString:groupRefresh];
}

- (BOOL)isStateStale:(NSDictionary *)state {
    NSDate *lastRefresh = [self lastRefreshDateFromState:state];
    if (!lastRefresh) {
        return YES;
    }

    NSNumber *ttl = NumberValue(state[@"state_file_ttl_seconds"]);
    NSTimeInterval ttlSeconds = ttl ? ttl.doubleValue : 180.0;
    return [[NSDate date] timeIntervalSinceDate:lastRefresh] > ttlSeconds;
}

- (void)addDisabledItemToMenu:(NSMenu *)menu title:(NSString *)title {
    NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:title action:nil keyEquivalent:@""];
    item.enabled = NO;
    [menu addItem:item];
}

- (void)addGroup:(NSDictionary *)group toMenu:(NSMenu *)menu {
    NSString *name = StringValue(group[@"name"]) ?: @"Rate limit";
    [self addDisabledItemToMenu:menu title:name];

    NSDictionary *fiveH = DictionaryValue(group[@"five_h"]);
    if (fiveH) {
        NSString *text = [NSString stringWithFormat:@"  5h: %@  reset %@",
                          [self percentString:[self remainingPercentForWindow:fiveH]],
                          [self detailTime:[self resetAtForWindow:fiveH]]];
        [self addDisabledItemToMenu:menu title:text];
    }

    NSDictionary *week = DictionaryValue(group[@"week"]);
    if (week) {
        NSString *text = [NSString stringWithFormat:@"  Weekly: %@  reset %@",
                          [self percentString:[self remainingPercentForWindow:week]],
                          [self shortDate:[self resetAtForWindow:week]]];
        [self addDisabledItemToMenu:menu title:text];
    }
}

- (NSString *)errorMessageFromState:(NSDictionary *)state {
    NSDictionary *error = DictionaryValue(state[@"error"]);
    return StringValue(error[@"message"]);
}

- (NSArray *)pendingApprovalsFromState:(NSDictionary *)approvalState {
    NSArray *approvals = ArrayValue(approvalState[@"approvals"]);
    if (!approvals) {
        return @[];
    }

    NSMutableArray *pending = [NSMutableArray array];
    for (id rawApproval in approvals) {
        NSDictionary *approval = DictionaryValue(rawApproval);
        if (approval) {
            [pending addObject:approval];
        }
    }
    return pending;
}

- (NSString *)approvalErrorMessageFromState:(NSDictionary *)approvalState {
    NSDictionary *error = DictionaryValue(approvalState[@"error"]);
    return StringValue(error[@"message"]);
}

- (NSString *)menuSafeText:(NSString *)text limit:(NSUInteger)limit {
    if (text.length <= limit) {
        return text;
    }
    if (limit <= 3) {
        return [text substringToIndex:limit];
    }
    return [[text substringToIndex:limit - 3] stringByAppendingString:@"..."];
}

- (BOOL)approvalPulseEnabled:(NSDictionary *)approvalState {
    NSNumber *pulse = NumberValue(approvalState[@"pulse"]);
    return pulse ? pulse.boolValue : YES;
}

- (BOOL)approvalNotificationsEnabled:(NSDictionary *)approvalState {
    NSNumber *notify = NumberValue(approvalState[@"notify"]);
    return notify ? notify.boolValue : YES;
}

- (void)setStatusDisplayForState:(NSDictionary *)state
                            stale:(BOOL)stale
                            title:(NSString *)quotaTitle
                        approvals:(NSArray *)approvals
                    approvalState:(NSDictionary *)approvalState {
    NSString *title = quotaTitle ?: @"quota --";
    BOOL hasApprovals = approvals.count > 0;
    if (hasApprovals) {
        title = [NSString stringWithFormat:@"APPROVAL %lu | %@", (unsigned long)approvals.count, title];
    }

    if (!self.statusItem.button) {
        return;
    }

    NSImage *statusImage = [self statusImageWithState:state
                                               stale:stale
                                           approvals:approvals
                                       approvalState:approvalState
                                       fallbackTitle:title];
    if (statusImage) {
        self.statusItem.length = statusImage.size.width + 8.0;
        self.statusItem.button.title = @"";
        self.statusItem.button.attributedTitle = [[NSAttributedString alloc] initWithString:@""];
        self.statusItem.button.image = statusImage;
        self.statusItem.button.imagePosition = NSImageOnly;
        self.statusItem.button.toolTip = title;
        return;
    }

    self.statusItem.length = NSVariableStatusItemLength;
    self.statusItem.button.image = nil;
    if (!hasApprovals) {
        self.statusItem.button.attributedTitle = [[NSAttributedString alloc] initWithString:title];
        return;
    }

    BOOL pulseEnabled = [self approvalPulseEnabled:approvalState];
    NSColor *color = (pulseEnabled && self.approvalPulseOn) ? NSColor.systemOrangeColor : NSColor.labelColor;
    NSDictionary *attributes = @{
        NSForegroundColorAttributeName: color,
        NSFontAttributeName: [NSFont systemFontOfSize:NSFont.systemFontSize weight:NSFontWeightSemibold]
    };
    self.statusItem.button.attributedTitle = [[NSAttributedString alloc] initWithString:title attributes:attributes];
}

- (void)ensurePulseTimerForApprovals:(NSArray *)approvals approvalState:(NSDictionary *)approvalState {
    BOOL shouldPulse = approvals.count > 0 && [self approvalPulseEnabled:approvalState];
    if (shouldPulse && !self.pulseTimer) {
        self.pulseTimer = [NSTimer scheduledTimerWithTimeInterval:1.0
                                                          target:self
                                                        selector:@selector(toggleApprovalPulse)
                                                        userInfo:nil
                                                         repeats:YES];
    } else if (!shouldPulse && self.pulseTimer) {
        [self.pulseTimer invalidate];
        self.pulseTimer = nil;
        self.approvalPulseOn = NO;
    }
}

- (void)toggleApprovalPulse {
    self.approvalPulseOn = !self.approvalPulseOn;
    [self updateMenu];
}

- (NSString *)approvalSummary:(NSDictionary *)approval {
    NSString *summary = StringValue(approval[@"summary"]);
    if (summary.length > 0) {
        return [self menuSafeText:summary limit:90];
    }
    NSString *title = StringValue(approval[@"title"]);
    return title.length > 0 ? title : @"Codex approval";
}

- (void)notifyForApprovals:(NSArray *)approvals approvalState:(NSDictionary *)approvalState {
    if (![self approvalNotificationsEnabled:approvalState]) {
        return;
    }

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    for (NSDictionary *approval in approvals) {
        NSString *approvalId = StringValue(approval[@"id"]);
        if (approvalId.length == 0 || [self.notifiedApprovalIds containsObject:approvalId]) {
            continue;
        }
        [self.notifiedApprovalIds addObject:approvalId];

        NSUserNotification *notification = [[NSUserNotification alloc] init];
        notification.title = @"Codex approval needed";
        notification.informativeText = [self approvalSummary:approval];
        notification.soundName = NSUserNotificationDefaultSoundName;
        [NSUserNotificationCenter.defaultUserNotificationCenter deliverNotification:notification];
    }
#pragma clang diagnostic pop
}

- (void)addApproval:(NSDictionary *)approval toMenu:(NSMenu *)menu {
    NSString *title = StringValue(approval[@"title"]) ?: @"Codex approval";
    NSString *summary = [self approvalSummary:approval];
    [self addDisabledItemToMenu:menu title:title];
    [self addDisabledItemToMenu:menu title:[@"  " stringByAppendingString:summary]];

    NSString *threadTitle = StringValue(approval[@"thread_title"]);
    if (threadTitle.length > 0) {
        [self addDisabledItemToMenu:menu title:[@"  Thread: " stringByAppendingString:[self menuSafeText:threadTitle limit:90]]];
    }
    NSString *cwd = StringValue(approval[@"cwd"]);
    if (cwd.length > 0) {
        [self addDisabledItemToMenu:menu title:[@"  Cwd: " stringByAppendingString:[self menuSafeText:cwd limit:100]]];
    }
    NSString *reason = StringValue(approval[@"reason"]);
    if (reason.length > 0) {
        [self addDisabledItemToMenu:menu title:[@"  Reason: " stringByAppendingString:[self menuSafeText:reason limit:100]]];
    }

    NSArray *decisions = ArrayValue(approval[@"decisions"]);
    NSString *approvalId = StringValue(approval[@"id"]);
    for (id rawDecision in decisions ?: @[]) {
        NSDictionary *decision = DictionaryValue(rawDecision);
        NSString *decisionId = StringValue(decision[@"id"]);
        NSString *label = StringValue(decision[@"label"]);
        if (approvalId.length == 0 || decisionId.length == 0 || label.length == 0) {
            continue;
        }
        NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:[@"  " stringByAppendingString:label]
                                                      action:@selector(approvalDecision:)
                                               keyEquivalent:@""];
        item.target = self;
        item.representedObject = @{@"approval_id": approvalId, @"decision": decisionId};
        [menu addItem:item];
    }
}

- (void)addApprovalsToMenu:(NSMenu *)menu approvalState:(NSDictionary *)approvalState approvals:(NSArray *)approvals loadError:(NSError *)loadError {
    if (approvals.count > 0) {
        [self addDisabledItemToMenu:menu title:[NSString stringWithFormat:@"Awaiting Approval (%lu)", (unsigned long)approvals.count]];
        for (NSDictionary *approval in approvals) {
            [self addApproval:approval toMenu:menu];
            [menu addItem:NSMenuItem.separatorItem];
        }
        NSMenuItem *openCodexItem = [[NSMenuItem alloc] initWithTitle:@"Open Codex" action:@selector(openCodex:) keyEquivalent:@"c"];
        openCodexItem.target = self;
        [menu addItem:openCodexItem];
        [menu addItem:NSMenuItem.separatorItem];
        return;
    }

    if (!approvalState && loadError.code == NSFileReadNoSuchFileError) {
        return;
    }

    NSString *approvalError = approvalState ? [self approvalErrorMessageFromState:approvalState] : loadError.localizedDescription;
    if (approvalError.length > 0) {
        [self addDisabledItemToMenu:menu title:[@"Approval watcher: " stringByAppendingString:[self menuSafeText:approvalError limit:120]]];
        [menu addItem:NSMenuItem.separatorItem];
    }
}

- (NSMenu *)menuForState:(NSDictionary *)state
               loadError:(NSError *)loadError
           approvalState:(NSDictionary *)approvalState
       approvalLoadError:(NSError *)approvalLoadError {
    BOOL stale = state ? [self isStateStale:state] : YES;
    NSString *title = state ? [self titleFromState:state stale:stale] : @"quota error";
    NSArray *approvals = [self pendingApprovalsFromState:approvalState];
    [self ensurePulseTimerForApprovals:approvals approvalState:approvalState];
    [self notifyForApprovals:approvals approvalState:approvalState];
    [self setStatusDisplayForState:state stale:stale title:title approvals:approvals approvalState:approvalState];

    NSMenu *menu = [[NSMenu alloc] initWithTitle:@"Codex Quota"];
    [self addDisabledItemToMenu:menu title:title];
    [menu addItem:NSMenuItem.separatorItem];

    [self addApprovalsToMenu:menu approvalState:approvalState approvals:approvals loadError:approvalLoadError];

    if (state) {
        NSArray *groups = ArrayValue(state[@"rate_limits"]);
        if (groups.count > 0) {
            for (id rawGroup in groups) {
                NSDictionary *group = DictionaryValue(rawGroup);
                if (!group) {
                    continue;
                }
                [self addGroup:group toMenu:menu];
                [menu addItem:NSMenuItem.separatorItem];
            }
        } else {
            NSDictionary *legacy = @{@"name": @"Rate limits remaining",
                                     @"five_h": DictionaryValue(state[@"five_h"]) ?: @{},
                                     @"week": DictionaryValue(state[@"week"]) ?: @{}};
            [self addGroup:legacy toMenu:menu];
            [menu addItem:NSMenuItem.separatorItem];
        }

        NSDate *lastRefresh = [self lastRefreshDateFromState:state];
        if (lastRefresh) {
            [self addDisabledItemToMenu:menu
                                  title:[NSString stringWithFormat:@"Updated: %@",
                                         [self.detailDateFormatter stringFromDate:lastRefresh]]];
        }
        if (stale) {
            [self addDisabledItemToMenu:menu title:@"Status: stale"];
        }

        NSString *stateError = [self errorMessageFromState:state];
        if (stateError.length > 0) {
            [self addDisabledItemToMenu:menu title:[@"Error: " stringByAppendingString:stateError]];
        }
    } else {
        NSString *message = loadError.localizedDescription ?: @"state file not found";
        [self addDisabledItemToMenu:menu title:[@"Error: " stringByAppendingString:message]];
        [self addDisabledItemToMenu:menu title:self.stateURL.path];
    }

    [menu addItem:NSMenuItem.separatorItem];

    NSMenuItem *fetchItem = [[NSMenuItem alloc] initWithTitle:@"Fetch Now" action:@selector(fetchNow:) keyEquivalent:@"f"];
    fetchItem.target = self;
    [menu addItem:fetchItem];

    NSMenuItem *refreshItem = [[NSMenuItem alloc] initWithTitle:@"Reload State" action:@selector(updateMenu) keyEquivalent:@"r"];
    refreshItem.target = self;
    [menu addItem:refreshItem];

    [menu addItem:NSMenuItem.separatorItem];

    NSMenuItem *readmeItem = [[NSMenuItem alloc] initWithTitle:@"Open README" action:@selector(openReadme:) keyEquivalent:@"o"];
    readmeItem.target = self;
    [menu addItem:readmeItem];

    NSMenuItem *stateItem = [[NSMenuItem alloc] initWithTitle:@"Open State File" action:@selector(openStateFile:) keyEquivalent:@"s"];
    stateItem.target = self;
    [menu addItem:stateItem];

    [menu addItem:NSMenuItem.separatorItem];

    NSMenuItem *quitItem = [[NSMenuItem alloc] initWithTitle:@"Quit" action:@selector(quit:) keyEquivalent:@"q"];
    quitItem.target = self;
    [menu addItem:quitItem];

    return menu;
}

- (void)updateMenu {
    NSError *error = nil;
    NSDictionary *state = [self loadState:&error];
    NSError *approvalError = nil;
    NSDictionary *approvalState = [self loadApprovalState:&approvalError];
    self.statusItem.menu = [self menuForState:state loadError:error approvalState:approvalState approvalLoadError:approvalError];
}

- (BOOL)appendApprovalDecision:(NSDictionary *)decision error:(NSError **)error {
    NSString *path = self.approvalDecisionsURL.path;
    NSString *directory = path.stringByDeletingLastPathComponent;
    if (![NSFileManager.defaultManager createDirectoryAtPath:directory
                                 withIntermediateDirectories:YES
                                                  attributes:nil
                                                       error:error]) {
        return NO;
    }

    if (![NSFileManager.defaultManager fileExistsAtPath:path]) {
        if (![NSFileManager.defaultManager createFileAtPath:path contents:nil attributes:nil]) {
            if (error) {
                *error = [NSError errorWithDomain:@"EasyCodexLimitCheck"
                                             code:1
                                         userInfo:@{NSLocalizedDescriptionKey: @"Could not create approval decisions file"}];
            }
            return NO;
        }
    }

    NSData *payload = [NSJSONSerialization dataWithJSONObject:decision options:0 error:error];
    if (!payload) {
        return NO;
    }
    NSMutableData *line = [NSMutableData dataWithData:payload];
    [line appendData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];

    NSFileHandle *handle = [NSFileHandle fileHandleForWritingAtPath:path];
    if (!handle) {
        if (error) {
            *error = [NSError errorWithDomain:@"EasyCodexLimitCheck"
                                         code:2
                                     userInfo:@{NSLocalizedDescriptionKey: @"Could not open approval decisions file"}];
        }
        return NO;
    }
    @try {
        [handle seekToEndOfFile];
        [handle writeData:line];
        [handle closeFile];
    } @catch (NSException *exception) {
        [handle closeFile];
        if (error) {
            *error = [NSError errorWithDomain:@"EasyCodexLimitCheck"
                                         code:3
                                     userInfo:@{NSLocalizedDescriptionKey: exception.reason ?: @"Could not write approval decision"}];
        }
        return NO;
    }
    return YES;
}

- (void)approvalDecision:(id)sender {
    NSMenuItem *item = (NSMenuItem *)sender;
    NSDictionary *represented = DictionaryValue(item.representedObject);
    NSString *approvalId = StringValue(represented[@"approval_id"]);
    NSString *decisionId = StringValue(represented[@"decision"]);
    if (approvalId.length == 0 || decisionId.length == 0) {
        return;
    }

    NSDictionary *decision = @{
        @"approval_id": approvalId,
        @"decision": decisionId,
        @"created_at": [self.isoFormatter stringFromDate:[NSDate date]]
    };
    NSError *error = nil;
    if (![self appendApprovalDecision:decision error:&error]) {
        NSLog(@"Failed to append approval decision: %@", error.localizedDescription);
    }
    [self updateMenu];
}

- (void)fetchNow:(id)sender {
    (void)sender;
    NSString *script = self.fetchScript;
    if (![NSFileManager.defaultManager isExecutableFileAtPath:script]) {
        [self updateMenu];
        return;
    }

    NSTask *task = [[NSTask alloc] init];
    task.launchPath = @"/bin/bash";
    task.arguments = @[script];

    NSMutableDictionary *environment = [NSMutableDictionary dictionaryWithDictionary:NSProcessInfo.processInfo.environment];
    environment[@"CODEX_QUOTA_STATE_PATH"] = self.stateURL.path;
    environment[@"CODEX_QUOTA_PLUGIN_PATH"] = self.pluginRoot;
    task.environment = environment;

    __weak typeof(self) weakSelf = self;
    task.terminationHandler = ^(NSTask *finishedTask) {
        (void)finishedTask;
        dispatch_async(dispatch_get_main_queue(), ^{
            [weakSelf updateMenu];
        });
    };

    @try {
        [task launch];
    } @catch (NSException *exception) {
        (void)exception;
        [self updateMenu];
    }
}

- (void)openReadme:(id)sender {
    (void)sender;
    NSString *readme = [self.pluginRoot stringByAppendingPathComponent:@"README.md"];
    [NSWorkspace.sharedWorkspace openURL:[NSURL fileURLWithPath:readme]];
}

- (void)openStateFile:(id)sender {
    (void)sender;
    [NSWorkspace.sharedWorkspace openURL:self.stateURL];
}

- (void)openCodex:(id)sender {
    (void)sender;
    NSTask *task = [[NSTask alloc] init];
    task.launchPath = @"/usr/bin/open";
    task.arguments = @[@"-a", @"Codex"];
    @try {
        [task launch];
    } @catch (NSException *exception) {
        (void)exception;
    }
}

- (void)quit:(id)sender {
    (void)sender;
    [NSApplication.sharedApplication terminate:nil];
}

@end

int main(int argc, const char *argv[]) {
    (void)argc;
    (void)argv;

    @autoreleasepool {
        NSApplication *application = NSApplication.sharedApplication;
        [application setActivationPolicy:NSApplicationActivationPolicyAccessory];
        AppDelegate *delegate = [[AppDelegate alloc] init];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
