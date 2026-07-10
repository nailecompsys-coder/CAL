import SwiftUI

/// Clinical Trust palette — **Asset Catalog only**.
/// Never add RGB constructors here. Add a `.colorset` under
/// `Images.xcassets`, then expose it as `Color("Clinical…")`.
/// Enforced by `.cursor/rules/swift-color-standard.mdc` + `check-native-guardrails.sh`.
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
  static let lavender = Color("ClinicalLavender")
  /// Portal `--meeting-cal` lilac wash (#DCC9F5).
  static let meeting = Color("ClinicalMeeting")
  /// Stronger lilac for small month/day signal dots.
  static let meetingStrong = Color("ClinicalMeetingStrong")
  /// Pastel rose for Block OR signals.
  static let block = Color("ClinicalBlock")
  /// Stronger rose for small Block OR dots.
  static let blockStrong = Color("ClinicalBlockStrong")
  static let ink = Color("ClinicalInk")
  static let muted = Color("ClinicalMuted")
  static let stroke = Color("ClinicalStroke")
  static let shadow = Color("ClinicalShadow")
  static let authAccent = Color("ClinicalAuthAccent")
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

/// Centered date/range stepper shared by Schedule Day / Week / Month.
struct ScheduleDateStepper: View {
  let title: String
  let subtitle: String?
  let previousAction: () -> Void
  let nextAction: () -> Void
  var onTitleTap: (() -> Void)?
  /// Shown when the user has stepped away from today / current range.
  var todayAction: (() -> Void)?
  var showsTodayButton: Bool = false

  var body: some View {
    HStack(spacing: 0) {
      Button(action: previousAction) {
        Image(systemName: "chevron.left")
          .font(.subheadline.weight(.semibold))
          .frame(width: 36, height: 36)
          .contentShape(Rectangle())
      }
      .buttonStyle(.plain)

      Button {
        onTitleTap?()
      } label: {
        VStack(spacing: 2) {
          Text(title)
            .font(.subheadline.weight(.semibold))
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
          .font(.caption.weight(.bold))
          .foregroundStyle(ClinicalPalette.teal)
          .padding(.horizontal, 8)
          .padding(.vertical, 6)
          .background(ClinicalPalette.tealSoft, in: Capsule())
          .buttonStyle(.plain)
      }

      Button(action: nextAction) {
        Image(systemName: "chevron.right")
          .font(.subheadline.weight(.semibold))
          .frame(width: 36, height: 36)
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
