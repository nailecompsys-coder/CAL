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
    HStack(spacing: 12) {
      legendItem("C", "Clinic")
      legendItem("O", "OR")
      legendItem("M", "Meeting")
      Spacer(minLength: 0)
      Text("Call: WG · date · ALT")
        .foregroundStyle(.secondary)
    }
    .font(.caption2)
    .foregroundStyle(ClinicalPalette.ink)
    .lineLimit(1)
    .minimumScaleFactor(0.8)
  }

  private func legendItem(_ code: String, _ label: String) -> some View {
    HStack(spacing: 3) {
      Text(code).font(.caption2.weight(.bold)).foregroundStyle(ClinicalPalette.teal)
      Text(label)
    }
  }
}

struct MonthSelectedDayAgenda: View {
  let day: ScheduleDay
  let openDayAction: () -> Void
  let coverAction: (ScheduleAssignment) -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        VStack(alignment: .leading, spacing: 2) {
          Text(day.date.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()))
            .font(.headline)
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

      if !day.mySchedule.filter({ $0.kind != "block_or" }).isEmpty {
        DaySection(title: "Clinic & OR") {
          ClinicOrScheduleList(dayId: day.id, items: day.mySchedule)
        }
      }

      if !day.meetings.isEmpty {
        DaySection(title: "Meetings") {
          ForEach(day.meetings.prefix(3)) { meeting in
            DayAgendaRow(
              systemImage: "person.2.fill",
              title: meeting.title,
              subtitle: meeting.timeRange,
              showsChevron: false
            )
          }
        }
      }
    }
  }
}

private struct MonthHeatmapCell: View {
  let cell: MonthCell
  let isSelected: Bool
  let selectAction: () -> Void

  var body: some View {
    Button(action: selectAction) {
      VStack(spacing: 4) {
        HStack(spacing: 1) {
          MonthCallInitials(text: cell.callInitials(group: "WG"))
          Text(cell.date.formatted(.dateTime.day()))
            .font(.subheadline.weight(cell.isToday || isSelected ? .bold : .semibold))
            .foregroundStyle(dayNumberColor)
            .layoutPriority(1)
          MonthCallInitials(text: cell.callInitials(group: "ALT"))
        }

        HStack(spacing: 3) {
          if cell.amCodes.isEmpty && cell.pmCodes.isEmpty {
            Text(" ").font(.caption2)
          } else {
            MonthPeriodCode(codes: cell.amCodes)
            MonthPeriodCode(codes: cell.pmCodes)
          }
        }
      }
      .padding(.horizontal, 2)
      .padding(.vertical, 6)
      .frame(maxWidth: .infinity, minHeight: 50)
      .opacity(cell.isCurrentMonth ? 1 : 0.4)
      .background(cellBackground, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      .overlay {
        RoundedRectangle(cornerRadius: 10, style: .continuous)
          .stroke(isSelected ? ClinicalPalette.teal : Color.clear, lineWidth: 1.5)
      }
    }
    .buttonStyle(.plain)
  }

  private var dayNumberColor: Color {
    cell.isToday ? ClinicalPalette.teal : ClinicalPalette.ink
  }

  /// One signal for approved time off: a soft tint. Today gets the teal number only.
  private var cellBackground: Color {
    cell.hasMyApprovedOff && cell.isCurrentMonth ? ClinicalPalette.mint.opacity(0.7) : ClinicalPalette.card
  }
}

private struct MonthCallInitials: View {
  let text: String

  var body: some View {
    Text(text)
      .font(.system(.caption2, design: .monospaced).weight(.medium))
      .foregroundStyle(.secondary)
      .lineLimit(1)
      .minimumScaleFactor(0.6)
      .frame(maxWidth: .infinity)
  }
}

/// AM or PM letters (C / O / M): bold teal when booked, muted when the block is empty.
private struct MonthPeriodCode: View {
  let codes: [PeriodCode]

  var body: some View {
    HStack(spacing: 0) {
      if codes.isEmpty {
        Text("·").foregroundStyle(Color.secondary.opacity(0.5))
      } else {
        ForEach(codes, id: \.letter) { code in
          Text(code.letter)
            .fontWeight(code.isActive ? .black : .regular)
            .foregroundStyle(code.isActive ? ClinicalPalette.teal : ClinicalPalette.muted.opacity(0.6))
        }
      }
    }
    .font(.caption2)
    .lineLimit(1)
    .minimumScaleFactor(0.7)
  }
}
