import SwiftUI

struct TimeOffInfoBanner: View {
  var body: some View {
    Label {
      Text("Pick a month to scan requested and approved time off before choosing your dates.")
        .font(.caption)
        .foregroundStyle(ClinicalPalette.muted)
        .fixedSize(horizontal: false, vertical: true)
    } icon: {
      Image(systemName: "info.circle.fill")
        .foregroundStyle(ClinicalPalette.teal)
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 9)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.tealSoft)
  }
}

struct MonthPillPicker: View {
  let months: [Date]
  @Binding var selectedMonth: Date
  private let columns = Array(repeating: GridItem(.flexible(), spacing: 7), count: 4)

  var body: some View {
    LazyVGrid(columns: columns, spacing: 7) {
      ForEach(months, id: \.self) { month in
        Button {
          selectedMonth = month
        } label: {
          Text(month.formatted(.dateTime.month(.abbreviated)))
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.85)
            .foregroundStyle(isSelected(month) ? .white : ClinicalPalette.teal)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 7)
            .background(isSelected(month) ? ClinicalPalette.teal : ClinicalPalette.cardStrong, in: Capsule())
            .overlay {
              Capsule()
                .stroke(ClinicalPalette.teal.opacity(isSelected(month) ? 0 : 0.24), lineWidth: 0.8)
            }
        }
        .buttonStyle(.plain)
      }
    }
    .padding(.vertical, 2)
  }

  private func isSelected(_ month: Date) -> Bool {
    Calendar.current.isDate(month, equalTo: selectedMonth, toGranularity: .month)
  }
}

struct MonthTimeOffList: View {
  let days: [ScheduleDay]

  private var visibleDays: [ScheduleDay] {
    days.filter { !$0.requestedOff.isEmpty || !$0.off.isEmpty }
  }

  var body: some View {
    if visibleDays.isEmpty {
      EmptyDashboardRow(title: "No requested or approved time off.")
    } else {
      VStack(alignment: .leading, spacing: 7) {
        ForEach(visibleDays) { day in
          MonthTimeOffDayRow(day: day)
        }
      }
    }
  }
}

private struct MonthTimeOffDayRow: View {
  let day: ScheduleDay

  var body: some View {
    VStack(alignment: .leading, spacing: 5) {
      Text(day.date.formatted(.dateTime.weekday(.abbreviated).month(.defaultDigits).day()))
        .font(.caption.weight(.semibold))
        .foregroundStyle(ClinicalPalette.ink)

      if !day.requestedOff.isEmpty {
        TimeOffStatusLine(label: "Requested", initials: day.requestedOff, tint: ClinicalPalette.amber, textColor: .orange)
      }

      if !day.off.isEmpty {
        TimeOffStatusLine(label: "Approved", initials: day.off, tint: ClinicalPalette.mint, textColor: ClinicalPalette.scrubInk)
      }
    }
    .padding(.vertical, 2)
  }
}

private struct TimeOffStatusLine: View {
  let label: String
  let initials: [String]
  let tint: Color
  let textColor: Color

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 7) {
      Text(label)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(ClinicalPalette.muted)
        .frame(width: 58, alignment: .leading)

      TimeOffInitialsPills(items: initials, tint: tint, textColor: textColor)
    }
  }
}

private struct TimeOffInitialsPills: View {
  let items: [String]
  let tint: Color
  let textColor: Color

  var body: some View {
    HStack(spacing: 5) {
      ForEach(items, id: \.self) { item in
        Text(item)
          .font(.caption2.weight(.semibold))
          .padding(.horizontal, 8)
          .padding(.vertical, 4)
          .background(tint.opacity(0.92), in: Capsule())
          .overlay {
            Capsule()
              .stroke(textColor.opacity(0.24), lineWidth: 0.75)
          }
          .foregroundStyle(textColor)
      }
    }
  }
}
