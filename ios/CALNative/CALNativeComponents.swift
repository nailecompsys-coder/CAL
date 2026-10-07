import SwiftUI

/// Clinical Trust palette — Asset Catalog only.
/// Add a `.colorset` under `Images.xcassets`, then expose it as `Color("Clinical…")`.
enum ClinicalPalette {
  static let pageTop = Color("ClinicalPageTop")
  static let pageMiddle = Color("ClinicalPageMiddle")
  static let pageBottom = Color("ClinicalPageBottom")
  static let card = Color("ClinicalCard")
  static let cardStrong = Color("ClinicalCardStrong")
  static let teal = Color("ClinicalTeal")
  static let tealSoft = Color("ClinicalTealSoft")
  static let scrub = Color("ClinicalScrub")
  static let scrubInk = Color("ClinicalScrubInk")
  static let porcelainChip = Color("ClinicalPorcelainChip")
  static let mint = Color("ClinicalMint")
  static let amber = Color("ClinicalAmber")
  /// Readable status/warning text — `amber` is a soft fill, not for type.
  static let warningText = Color.orange
  static let lavender = Color("ClinicalLavender")
  static let meeting = Color("ClinicalMeeting")
  static let meetingStrong = Color("ClinicalMeetingStrong")
  static let block = Color("ClinicalBlock")
  static let blockStrong = Color("ClinicalBlockStrong")
  static let ink = Color("ClinicalInk")
  static let muted = Color("ClinicalMuted")
  static let stroke = Color("ClinicalStroke")
  static let shadow = Color("ClinicalShadow")
  static let authAccent = Color("ClinicalAuthAccent")

  /// One color per site; a location code's site is the part before "-" (AL-OR, AL-OV → AL).
  static func site(_ locationCode: String) -> Color {
    let site = locationCode.split(separator: "-").first.map { $0.uppercased() } ?? ""
    switch site {
    case "AL": return Color("ClinicalSiteAl")
    case "AP": return Color("ClinicalSiteAp")
    case "MN": return Color("ClinicalSiteMn")
    case "WG": return Color("ClinicalSiteWg")
    case "CL": return Color("ClinicalSiteCl")
    case "DP": return Color("ClinicalSiteDp")
    case "LM": return Color("ClinicalSiteLm")
    case "CBO": return Color("ClinicalSiteCbo")
    case "FL": return Color("ClinicalSiteFl")
    default: return muted
    }
  }
}

/// Location code chip: the OR is the solid site color, the office is its light tint.
struct LocationChip: View {
  let code: String

  private var isOR: Bool { code.uppercased().hasSuffix("-OR") }
  private var siteColor: Color { ClinicalPalette.site(code) }

  var body: some View {
    Text(code)
      .font(ClinicalTypography.monoChip)
      .lineLimit(1)
      .fixedSize()
      .padding(.horizontal, 7)
      .padding(.vertical, 2)
      .foregroundStyle(isOR ? Color.white : ClinicalPalette.ink)
      .background(isOR ? siteColor : siteColor.opacity(0.28), in: Capsule())
      .overlay { Capsule().stroke(siteColor, lineWidth: 1) }
  }
}

/// Small outlined status tag (Off, No Call, Call).
struct StatusTag: View {
  let text: String
  var tint: Color = ClinicalPalette.muted

  var body: some View {
    Text(text)
      .font(ClinicalTypography.badge)
      .lineLimit(1)
      .fixedSize()
      .padding(.horizontal, 6)
      .padding(.vertical, 2)
      .foregroundStyle(tint)
      .overlay { Capsule().stroke(tint.opacity(0.6), lineWidth: 0.75) }
  }
}

enum ClinicalTypography {
  static let largeTitle = Font.largeTitle.weight(.bold)
  static let headline = Font.headline.weight(.semibold)
  static let headlineStrong = Font.headline.weight(.black)
  static let rowTitle = Font.subheadline.weight(.semibold)
  static let rowTitleStrong = Font.subheadline.weight(.bold)
  static let sectionLabel = Font.caption.weight(.black)
  static let caption = Font.caption.weight(.semibold)
  static let captionEmphasized = Font.caption2.weight(.semibold)
  static let badge = Font.caption2.weight(.black)
  static let monoCaption = Font.caption.monospacedDigit().weight(.semibold)
  static let monoTitle = Font.system(.title3, design: .monospaced).weight(.bold)
  static let monoRow = Font.system(.subheadline, design: .monospaced).weight(.bold)
  static let monoChip = Font.system(.caption, design: .monospaced).weight(.semibold)
}

enum ClinicalLayout {
  static let authColumn: CGFloat = 520
  static let contentColumn: CGFloat = 840
  static let wideColumn: CGFloat = .infinity
}

enum ClinicalCalendar {
  /// Work week Monday–Sunday (not locale Sunday–Saturday).
  static var mondayFirst: Calendar {
    var calendar = Calendar.current
    calendar.firstWeekday = 2
    return calendar
  }
}

/// Horizontal chips when they fit; adaptive grid when they do not.
struct AdaptiveChipRow<Content: View>: View {
  var minimumChipWidth: CGFloat = 96
  var spacing: CGFloat = 8
  @ViewBuilder var content: () -> Content

  var body: some View {
    if #available(iOS 16.0, *) {
      ViewThatFits(in: .horizontal) {
        HStack(alignment: .center, spacing: spacing) {
          content()
        }
        LazyVGrid(
          columns: [GridItem(.adaptive(minimum: minimumChipWidth), spacing: spacing)],
          alignment: .leading,
          spacing: spacing
        ) {
          content()
        }
      }
    } else {
      LazyVGrid(
        columns: [GridItem(.adaptive(minimum: minimumChipWidth), spacing: spacing)],
        alignment: .leading,
        spacing: spacing
      ) {
        content()
      }
    }
  }
}

struct ScheduleWaterBackground: View {
  var body: some View {
    LinearGradient(
      colors: [
        ClinicalPalette.pageTop,
        ClinicalPalette.pageMiddle,
        ClinicalPalette.pageBottom
      ],
      startPoint: .topLeading,
      endPoint: .bottomTrailing
    )
    .ignoresSafeArea()
  }
}

struct DashboardSection<Content: View>: View {
  let title: String
  var tint: Color = ClinicalPalette.card
  @ViewBuilder let content: Content

  var body: some View {
    VStack(alignment: .leading, spacing: 5) {
      Text(title)
        .font(.caption.weight(.semibold))
        .foregroundStyle(ClinicalPalette.muted)
        .padding(.horizontal, 2)

      VStack(spacing: 6) {
        content
      }
      .padding(.horizontal, 12)
      .padding(.vertical, 9)
      .frame(maxWidth: .infinity, alignment: .leading)
      .liquidGlassCard(cornerRadius: 16, tint: tint)
    }
  }
}

/// Plain inset card for the Calendar day view: solid card fill, soft shadow, no tint.
struct CalCardModifier: ViewModifier {
  var padding: CGFloat = 14

  func body(content: Content) -> some View {
    content
      .padding(padding)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(ClinicalPalette.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
      .shadow(color: ClinicalPalette.shadow.opacity(0.08), radius: 10, x: 0, y: 3)
  }
}

extension View {
  func calCard(padding: CGFloat = 14) -> some View {
    modifier(CalCardModifier(padding: padding))
  }
}

/// Titled day-view section: headline title above a plain card.
struct DaySection<Content: View>: View {
  let title: String
  @ViewBuilder let content: Content

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text(title)
        .font(.headline)
        .foregroundStyle(ClinicalPalette.ink)
        .padding(.horizontal, 4)
      VStack(alignment: .leading, spacing: 12) {
        content
      }
      .calCard()
    }
  }
}

/// Two-line tappable day-view row: title, secondary line, trailing chevron.
struct DayAgendaRow: View {
  let systemImage: String
  let title: String
  let subtitle: String
  var isMuted = false
  var showsChevron = true

  var body: some View {
    HStack(spacing: 12) {
      Image(systemName: systemImage)
        .font(.body.weight(.semibold))
        .foregroundStyle(isMuted ? ClinicalPalette.muted : ClinicalPalette.teal)
      VStack(alignment: .leading, spacing: 2) {
        Text(title)
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(isMuted ? ClinicalPalette.muted : ClinicalPalette.ink)
          .multilineTextAlignment(.leading)
        if !subtitle.isEmpty {
          Text(subtitle)
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(1)
        }
      }
      Spacer(minLength: 0)
      if showsChevron {
        Image(systemName: "chevron.right")
          .font(.caption.weight(.semibold))
          .foregroundStyle(.tertiary)
      }
    }
    .contentShape(Rectangle())
  }
}

struct EmptyDashboardRow: View {
  let title: String

  var body: some View {
    Label(title, systemImage: "checkmark.circle")
      .font(.caption)
      .foregroundStyle(.secondary)
      .padding(.vertical, 1)
  }
}

struct CompactDatePickerRow: View {
  let title: String
  @Binding var date: Date

  var body: some View {
    DatePicker(title, selection: $date, displayedComponents: .date)
      .font(.subheadline)
  }
}

/// Shared date stepper for Schedule Day / Week / Month.
struct ScheduleDateStepper: View {
  let title: String
  let subtitle: String?
  let previousAction: () -> Void
  let nextAction: () -> Void
  var onTitleTap: (() -> Void)?
  var todayAction: (() -> Void)?
  var showsTodayButton: Bool = false
  @ScaledMetric(relativeTo: .body) private var controlSize: CGFloat = 36

  var body: some View {
    HStack(spacing: 0) {
      Button(action: previousAction) {
        Image(systemName: "chevron.left")
          .font(ClinicalTypography.rowTitle)
          .frame(width: controlSize, height: controlSize)
          .contentShape(Rectangle())
      }
      .buttonStyle(.plain)

      Button {
        onTitleTap?()
      } label: {
        VStack(spacing: 2) {
          Text(title)
            .font(ClinicalTypography.rowTitle)
            .foregroundStyle(ClinicalPalette.ink)
            .lineLimit(1)
            .minimumScaleFactor(0.85)
          if let subtitle, !subtitle.isEmpty {
            Text(subtitle)
              .font(.caption2)
              .foregroundStyle(.secondary)
              .lineLimit(1)
          }
        }
        .frame(maxWidth: .infinity)
      }
      .buttonStyle(.plain)
      .disabled(onTitleTap == nil)

      if showsTodayButton, let todayAction {
        Button("Today", action: todayAction)
          .font(ClinicalTypography.caption)
          .foregroundStyle(ClinicalPalette.teal)
          .padding(.horizontal, 8)
          .padding(.vertical, 6)
          .background(ClinicalPalette.tealSoft, in: Capsule())
          .buttonStyle(.plain)
      }

      Button(action: nextAction) {
        Image(systemName: "chevron.right")
          .font(ClinicalTypography.rowTitle)
          .frame(width: controlSize, height: controlSize)
          .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
    }
    .padding(.horizontal, 8)
    .padding(.vertical, 6)
    .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.cardStrong)
  }
}

extension View {
  @ViewBuilder
  func scrollContentBackgroundHiddenIfAvailable() -> some View {
    if #available(iOS 16.0, *) {
      self.scrollContentBackground(.hidden)
    } else {
      self
    }
  }

  /// Keep NavigationView single-column on iPad (avoids empty detail pane).
  /// Must be applied to the NavigationView, not its root content.
  func calStackNavigation() -> some View {
    navigationViewStyle(.stack)
  }

  /// Center content on regular-width size classes (iPad / landscape).
  func calReadableColumn(_ maxWidth: CGFloat = ClinicalLayout.contentColumn) -> some View {
    modifier(CalReadableColumnModifier(maxWidth: maxWidth))
  }

  func liquidGlassCard(
    cornerRadius: CGFloat = 18,
    tint: Color = ClinicalPalette.card
  ) -> some View {
    self
      .background {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
          .fill(.thinMaterial)
          .overlay(tint.opacity(0.68))
      }
      .overlay {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
          .stroke(
            LinearGradient(
              colors: [
                Color.white.opacity(0.96),
                ClinicalPalette.stroke.opacity(0.44),
                tint.opacity(0.84)
              ],
              startPoint: .topLeading,
              endPoint: .bottomTrailing
            ),
            lineWidth: 1
          )
      }
      .shadow(color: ClinicalPalette.shadow.opacity(0.12), radius: 14, x: 0, y: 8)
      .shadow(color: Color.white.opacity(0.80), radius: 1, x: 0, y: -1)
  }
}

private struct CalReadableColumnModifier: ViewModifier {
  @Environment(\.horizontalSizeClass) private var horizontalSizeClass
  let maxWidth: CGFloat

  func body(content: Content) -> some View {
    content
      .frame(maxWidth: horizontalSizeClass == .regular ? maxWidth : .infinity)
      .frame(maxWidth: .infinity)
  }
}

/// Single-column navigation on iPhone and iPad (NavigationStack when available).
struct CalNavigation<Content: View>: View {
  @ViewBuilder var content: () -> Content

  var body: some View {
    if #available(iOS 16.0, *) {
      NavigationStack {
        content()
      }
    } else {
      NavigationView {
        content()
      }
      .navigationViewStyle(.stack)
    }
  }
}
