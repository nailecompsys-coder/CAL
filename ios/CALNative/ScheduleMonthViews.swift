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
      Text("Call WG · ALT under date, backup bold")
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

      if !day.mySchedule.isEmpty {
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

  private var wg: String { cell.callInitials(group: "WG") }
  private var alt: String { cell.callInitials(group: "ALT") }
  private var wgBackup: String { cell.backupCallInitials(group: "WG") }
  private var altBackup: String { cell.backupCallInitials(group: "ALT") }

  var body: some View {
    Button(action: selectAction) {
      VStack(spacing: 3) {
        Text(cell.date.formatted(.dateTime.day()))
          .font(.subheadline.weight(cell.isToday || isSelected ? .bold : .semibold))
          .foregroundStyle(dayNumberColor)
          .frame(maxWidth: .infinity)

        HStack(spacing: 3) {
          if cell.amCodes.isEmpty && cell.pmCodes.isEmpty {
            Text(" ").font(.caption2)
          } else {
            MonthPeriodCode(codes: cell.amCodes)
            MonthPeriodCode(codes: cell.pmCodes)
          }
        }
        .frame(maxWidth: .infinity)

        MonthCallInitials(groups: [(wg, wgBackup), (alt, altBackup)])
          .frame(maxWidth: .infinity)
      }
      .padding(.horizontal, 2)
      .padding(.vertical, 5)
      .frame(maxWidth: .infinity, minHeight: 56)
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

/// Call initials under the date, WG first then ALT (positional).
/// No backup that day: the original "WG · ALT" with the separator.
/// A backup that day: no separator; each group's primary then its backup in bold ("LW JD **NF**").
/// An empty group shows "--" in backup mode so the remaining initials keep their position.
private struct MonthCallInitials: View {
  let groups: [(primary: String, backup: String)]

  private var hasBackup: Bool { groups.contains { !$0.backup.isEmpty } }
  private var allEmpty: Bool { groups.allSatisfy { $0.primary.isEmpty && $0.backup.isEmpty } }

  private func primaryText(_ value: String) -> Text {
    Text(value.isEmpty ? (hasBackup ? "--" : " ") : value)
      .fontWeight(.semibold)
      .foregroundColor(.secondary)
  }

  private var line: Text {
    if allEmpty { return Text(" ") }
    var joined: Text?
    for group in groups {
      var part = primaryText(group.primary)
      if !group.backup.isEmpty {
        part = part + Text(" ") + Text(group.backup).fontWeight(.black).foregroundColor(ClinicalPalette.ink)
      }
      if let prev = joined {
        let separator = hasBackup
          ? Text(" ")
          : Text(" · ").foregroundColor(ClinicalPalette.muted.opacity(0.55))
        joined = prev + separator + part
      } else {
        joined = part
      }
    }
    return joined ?? Text(" ")
  }

  var body: some View {
    line
      .font(.system(.caption2, design: .monospaced))
      .lineLimit(1)
      .minimumScaleFactor(0.5)
      .multilineTextAlignment(.center)
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
