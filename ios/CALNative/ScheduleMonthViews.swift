import SwiftUI

struct MonthGridView: View {
  let cells: [MonthCell]
  @Binding var selectedDate: Date
  /// Kept for API compatibility with callers; month cells no longer jump scope.
  @Binding var scope: ScheduleScope
  let coverAction: (ScheduleAssignment) -> Void

  private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 7)

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      MonthDotLegend()

      LazyVGrid(columns: columns, spacing: 4) {
        ForEach(Calendar.current.shortWeekdaySymbols, id: \.self) { day in
          Text(String(day.prefix(1)))
            .font(.caption2.weight(.bold))
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity)
        }

        ForEach(cells) { cell in
          MonthHeatmapCell(
            cell: cell,
            isSelected: Calendar.current.isDate(cell.date, inSameDayAs: selectedDate)
          ) {
            withAnimation(.easeInOut(duration: 0.15)) {
              selectedDate = cell.date
            }
          }
        }
      }
    }
    .padding(.vertical, 4)
  }
}

private struct MonthDotLegend: View {
  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      Text("Your month")
        .font(ClinicalTypography.captionEmphasized)
        .foregroundStyle(ClinicalPalette.muted)

      AdaptiveChipRow(minimumChipWidth: 88, spacing: 10) {
        legendOff
        legendDot(color: ClinicalPalette.amber, label: "Clinic/OR")
        legendDot(color: ClinicalPalette.blockStrong, label: "Block")
        legendDot(color: ClinicalPalette.meetingStrong, label: "Meeting")
      }
    }
    .font(ClinicalTypography.captionEmphasized)
    .foregroundStyle(ClinicalPalette.ink.opacity(0.75))
  }

  private var legendOff: some View {
    HStack(spacing: 4) {
      Text("OFF")
        .font(ClinicalTypography.badge)
        .foregroundStyle(ClinicalPalette.scrubInk)
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(ClinicalPalette.mint, in: RoundedRectangle(cornerRadius: 3, style: .continuous))
      Text("Off")
        .lineLimit(1)
        .minimumScaleFactor(0.85)
    }
  }

  private func legendDot(color: Color, label: String) -> some View {
    HStack(spacing: 4) {
      MonthSignalDot(color: color)
      Text(label)
        .lineLimit(1)
        .minimumScaleFactor(0.85)
    }
  }
}

private struct MonthSignalDot: View {
  let color: Color
  @ScaledMetric(relativeTo: .caption2) private var size: CGFloat = 9

  var body: some View {
    ZStack {
      Circle()
        .fill(Color.white)
        .frame(width: size + 2, height: size + 2)
      Circle()
        .fill(color)
        .frame(width: size, height: size)
    }
  }
}

struct MonthSelectedDayAgenda: View {
  let day: ScheduleDay
  let openDayAction: () -> Void
  let coverAction: (ScheduleAssignment) -> Void
  var openPatientsAction: (() -> Void)?

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        VStack(alignment: .leading, spacing: 2) {
          Text(day.date.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()))
            .font(.subheadline.weight(.semibold))
          Text(day.hasMyApprovedOff ? "Approved day off" : "Selected day")
            .font(.caption2.weight(day.hasMyApprovedOff ? .bold : .regular))
            .foregroundStyle(day.hasMyApprovedOff ? ClinicalPalette.scrubInk : .secondary)
        }
        Spacer()
        Button("Open Day", action: openDayAction)
          .font(.caption.weight(.semibold))
          .buttonStyle(.bordered)
          .tint(ClinicalPalette.teal)
      }

      ScheduleDailyGlanceCard(day: day, coverAction: coverAction)

      if !day.mySchedule.isEmpty {
        VStack(alignment: .leading, spacing: 4) {
          Text("Clinic / OR")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
          ForEach(day.mySchedule.prefix(4)) { item in
            MyScheduleRow(item: item, openPatientsAction: openPatientsAction)
          }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)
      }

      if !day.meetings.isEmpty {
        VStack(alignment: .leading, spacing: 4) {
          Text("Meetings")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
          ForEach(day.meetings.prefix(3)) { meeting in
            Text([meeting.timeRange, meeting.title].filter { !$0.isEmpty }.joined(separator: " · "))
              .font(.caption.weight(.medium))
              .foregroundStyle(ClinicalPalette.ink)
              .lineLimit(2)
          }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.meeting)
      }
    }
  }
}

private struct MonthHeatmapCell: View {
  let cell: MonthCell
  let isSelected: Bool
  let selectAction: () -> Void

  private var hasSignals: Bool {
    cell.hasMyApprovedOff || cell.hasClinicOr || cell.hasBlockTime || cell.hasMeeting
  }

  var body: some View {
    Button(action: selectAction) {
      VStack(spacing: 4) {
        Text(cell.date.formatted(.dateTime.day()))
          .font(.caption.weight(isSelected || cell.isToday || cell.hasMyApprovedOff ? .bold : .semibold))
          .foregroundStyle(dayNumberColor)

        if cell.hasMyApprovedOff {
          Text("OFF")
            .font(ClinicalTypography.badge)
            .foregroundStyle(ClinicalPalette.scrubInk)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 2)
            .background(ClinicalPalette.mint, in: RoundedRectangle(cornerRadius: 4, style: .continuous))
            .overlay {
              RoundedRectangle(cornerRadius: 4, style: .continuous)
                .stroke(ClinicalPalette.scrubInk.opacity(0.35), lineWidth: 1)
            }
        }

        HStack(spacing: 3) {
          if cell.hasClinicOr {
            MonthSignalDot(color: ClinicalPalette.amber)
          }
          if cell.hasBlockTime {
            MonthSignalDot(color: ClinicalPalette.blockStrong)
          }
          if cell.hasMeeting {
            MonthSignalDot(color: ClinicalPalette.meetingStrong)
          }
          if !hasSignals {
            MonthSignalDot(color: .clear).opacity(0)
          }
        }
        .frame(minHeight: 11)
      }
      .padding(.horizontal, 2)
      .padding(.vertical, 5)
      .frame(maxWidth: .infinity, minHeight: 52)
      .background(cellBackground, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      .overlay {
        RoundedRectangle(cornerRadius: 10, style: .continuous)
          .stroke(borderColor, lineWidth: borderWidth)
      }
    }
    .buttonStyle(.plain)
  }

  private var dayNumberColor: Color {
    if !cell.isCurrentMonth {
      return .secondary
    }
    if cell.hasMyApprovedOff {
      return ClinicalPalette.scrubInk
    }
    if isSelected || cell.isToday {
      return ClinicalPalette.teal
    }
    return ClinicalPalette.ink
  }

  private var cellBackground: Color {
    if cell.hasMyApprovedOff {
      return ClinicalPalette.mint.opacity(isSelected ? 0.95 : 0.72)
    }
    if isSelected {
      return ClinicalPalette.tealSoft.opacity(0.9)
    }
    if cell.isToday {
      return ClinicalPalette.tealSoft.opacity(0.55)
    }
    if !cell.isCurrentMonth {
      return Color.white.opacity(0.35)
    }
    return ClinicalPalette.card.opacity(0.7)
  }

  private var borderColor: Color {
    if cell.hasMyApprovedOff {
      return ClinicalPalette.scrubInk.opacity(isSelected ? 0.7 : 0.45)
    }
    if isSelected {
      return ClinicalPalette.teal
    }
    if cell.isToday {
      return ClinicalPalette.teal.opacity(0.45)
    }
    return Color.clear
  }

  private var borderWidth: CGFloat {
    if cell.hasMyApprovedOff || isSelected {
      return 1.5
    }
    return cell.isToday ? 1 : 0
  }
}
