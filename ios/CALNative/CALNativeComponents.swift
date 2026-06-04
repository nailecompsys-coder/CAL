import SwiftUI

enum ClinicalPalette {
  static let pageTop = Color(red: 0.94, green: 0.98, blue: 0.98)
  static let pageMiddle = Color(red: 0.99, green: 1.00, blue: 0.98)
  static let pageBottom = Color(red: 0.93, green: 0.98, blue: 0.95)
  static let card = Color(red: 0.99, green: 1.00, blue: 0.98)
  static let cardStrong = Color(red: 1.00, green: 1.00, blue: 0.97)
  static let teal = Color(red: 0.00, green: 0.46, blue: 0.50)
  static let tealSoft = Color(red: 0.76, green: 0.93, blue: 0.90)
  static let scrub = Color(red: 0.82, green: 0.94, blue: 0.84)
  static let scrubInk = Color(red: 0.10, green: 0.42, blue: 0.30)
  static let porcelainChip = Color(red: 0.97, green: 0.98, blue: 0.95)
  static let mint = Color(red: 0.88, green: 0.97, blue: 0.88)
  static let amber = Color(red: 1.00, green: 0.92, blue: 0.74)
  static let lavender = Color(red: 0.94, green: 0.91, blue: 1.00)
  static let ink = Color(red: 0.07, green: 0.12, blue: 0.15)
  static let muted = Color(red: 0.36, green: 0.43, blue: 0.46)
  static let stroke = Color(red: 0.70, green: 0.82, blue: 0.82)
  static let shadow = Color(red: 0.08, green: 0.24, blue: 0.24)
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
