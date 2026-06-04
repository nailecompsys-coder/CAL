import SwiftUI

struct CompactRangeHeader: View {
  let title: String
  let subtitle: String
  let previousAction: () -> Void
  let nextAction: () -> Void

  var body: some View {
    HStack {
      VStack(alignment: .leading, spacing: 2) {
        Text(title)
          .font(.subheadline.weight(.semibold))
        Text(subtitle)
          .font(.caption2)
          .foregroundStyle(.secondary)
      }

      Spacer()

      HStack(spacing: 10) {
        Button(action: previousAction) {
          Image(systemName: "chevron.left")
        }

        Button(action: nextAction) {
          Image(systemName: "chevron.right")
        }
      }
      .font(.subheadline.weight(.semibold))
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 9)
    .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.cardStrong)
  }
}

struct CompactWeekDayCard: View {
  let day: ScheduleDay
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope
  let coverAction: (ScheduleAssignment) -> Void

  var body: some View {
    HStack(alignment: .top, spacing: 10) {
      VStack(spacing: 1) {
        Text(day.date.formatted(.dateTime.weekday(.abbreviated)))
          .font(.caption2.weight(.bold))
          .foregroundStyle(.secondary)
        Text(day.date.formatted(.dateTime.day()))
          .font(.subheadline.weight(.bold))
          .foregroundStyle(Calendar.current.isDateInToday(day.date) ? ClinicalPalette.teal : ClinicalPalette.ink)
      }
      .frame(width: 34)
      .contentShape(Rectangle())
      .onTapGesture {
        openDay()
      }

      VStack(alignment: .leading, spacing: 6) {
        ScheduleAssignmentActionLine(
          prefix: "ON",
          assignments: Array(day.assignments.prefix(3)),
          tint: ClinicalPalette.teal,
          action: coverAction
        )

        ScheduleStatusLine(
          prefix: "OFF",
          value: day.off.prefix(4).joined(separator: " / "),
          tint: ClinicalPalette.teal
        )
      }
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 9)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 16, tint: Calendar.current.isDateInToday(day.date) ? ClinicalPalette.tealSoft : ClinicalPalette.card)
  }

  private func openDay() {
    withAnimation(.snappy(duration: 0.22)) {
      selectedDate = day.date
      scope = .day
    }
  }
}

private struct ScheduleAssignmentActionLine: View {
  let prefix: String
  let assignments: [ScheduleAssignment]
  let tint: Color
  let action: (ScheduleAssignment) -> Void

  var body: some View {
    HStack(spacing: 6) {
      Text(prefix)
        .font(.caption2.weight(.bold))
        .foregroundStyle(tint)
        .frame(width: 28, alignment: .leading)

      if assignments.isEmpty {
        Text("None")
          .font(.caption.weight(.medium))
          .foregroundStyle(.secondary)
      } else {
        HStack(spacing: 4) {
          ForEach(assignments) { assignment in
            Button {
              action(assignment)
            } label: {
              SmallCoverageInitialsView(assignment: assignment)
            }
            .buttonStyle(.plain)
            .disabled(assignment.rotationId == nil)
          }
        }
      }
    }
    .frame(maxWidth: .infinity, alignment: .leading)
  }
}

private struct SmallCoverageInitialsView: View {
  let assignment: ScheduleAssignment

  var body: some View {
    if assignment.isCovered {
      HStack(spacing: 2) {
        StruckInitialsText(
          text: assignment.originalInitials,
          font: .system(.caption, design: .rounded).weight(.semibold)
        )
        Text(assignment.coveringInitials ?? assignment.surgeon)
          .font(.system(.caption, design: .rounded).weight(.semibold))
          .foregroundStyle(.primary)
      }
      .padding(.horizontal, 3)
      .padding(.vertical, 1)
      .background(ClinicalPalette.teal.opacity(0.08), in: Capsule())
    } else {
      Text(assignment.surgeon)
        .font(.system(.caption, design: .rounded).weight(.semibold))
        .foregroundStyle(.primary)
        .padding(.horizontal, 4)
        .padding(.vertical, 1)
        .background(ClinicalPalette.teal.opacity(0.08), in: Capsule())
    }
  }
}

private struct LegacyCompactWeekDayCard: View {
  let day: ScheduleDay
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope

  var body: some View {
    Button {
      withAnimation(.snappy(duration: 0.22)) {
        selectedDate = day.date
        scope = .day
      }
    } label: {
      HStack(alignment: .top, spacing: 10) {
        VStack(spacing: 1) {
          Text(day.date.formatted(.dateTime.weekday(.abbreviated)))
            .font(.caption2.weight(.bold))
            .foregroundStyle(.secondary)
          Text(day.date.formatted(.dateTime.day()))
            .font(.subheadline.weight(.bold))
            .foregroundStyle(Calendar.current.isDateInToday(day.date) ? ClinicalPalette.teal : ClinicalPalette.ink)
        }
        .frame(width: 34)

        VStack(alignment: .leading, spacing: 6) {
          ScheduleStatusLine(
            prefix: "ON",
            value: day.assignments.map(\.surgeon).prefix(3).joined(separator: " / "),
            tint: ClinicalPalette.teal
          )

          ScheduleStatusLine(
            prefix: "OFF",
            value: day.off.prefix(4).joined(separator: " / "),
            tint: ClinicalPalette.teal
          )
        }
      }
      .padding(.horizontal, 12)
      .padding(.vertical, 9)
      .frame(maxWidth: .infinity, alignment: .leading)
      .liquidGlassCard(cornerRadius: 16, tint: Calendar.current.isDateInToday(day.date) ? ClinicalPalette.tealSoft : ClinicalPalette.card)
    }
    .buttonStyle(.plain)
  }
}

private struct WeekDaySection: View {
  let day: ScheduleDay
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope

  var body: some View {
    Section {
      Button {
        selectedDate = day.date
        scope = .day
      } label: {
        VStack(alignment: .leading, spacing: 10) {
          HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
              Text(day.date.formatted(.dateTime.weekday(.wide)))
                .font(.headline)
              Text(day.date.formatted(.dateTime.month(.abbreviated).day()))
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer()

            if !day.off.isEmpty {
              FlowLine(items: day.off)
            }
          }

          ForEach(day.assignments) { assignment in
            CompactAssignmentLine(assignment: assignment)
          }

          if !day.personalItems.isEmpty {
            Label(day.personalItems.joined(separator: ", "), systemImage: "note.text")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
        }
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
    }
  }
}

private struct AssignmentRow: View {
  let assignment: ScheduleAssignment

  var body: some View {
    HStack(spacing: 12) {
      Image(systemName: assignment.systemImage)
        .foregroundStyle(ClinicalPalette.teal)
        .frame(width: 28)

      VStack(alignment: .leading, spacing: 3) {
        Text(assignment.location)
          .font(.body)
        Text(assignment.time)
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      Spacer()

      Text(assignment.surgeon)
        .font(.system(.headline, design: .monospaced))
        .foregroundStyle(.primary)
    }
    .padding(.vertical, 3)
  }
}

private struct CompactAssignmentLine: View {
  let assignment: ScheduleAssignment

  var body: some View {
    HStack(spacing: 8) {
      Text(assignment.locationShort)
        .font(.caption.weight(.semibold))
        .foregroundStyle(.primary)
      Spacer()
      Text(assignment.surgeon)
        .font(.system(.caption, design: .monospaced).weight(.semibold))
        .foregroundStyle(.secondary)
    }
  }
}

private struct ScheduleStatusLine: View {
  let prefix: String
  let value: String
  let tint: Color

  var body: some View {
    HStack(spacing: 6) {
      Text(prefix)
        .font(.caption2.weight(.bold))
        .foregroundStyle(tint)
        .frame(width: 28, alignment: .leading)

      if value.isEmpty {
        Text("None")
          .font(.caption.weight(.medium))
          .foregroundStyle(.secondary)
      } else {
        Text(value)
          .font(.system(.caption, design: .rounded).weight(.semibold))
          .foregroundStyle(.primary)
          .lineLimit(1)
          .minimumScaleFactor(0.72)
      }
    }
    .frame(maxWidth: .infinity, alignment: .leading)
  }
}

struct MonthGridView: View {
  let cells: [MonthCell]
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope
  let coverAction: (ScheduleAssignment) -> Void

  private let columns = Array(repeating: GridItem(.flexible(), spacing: 6), count: 7)

  var body: some View {
    VStack(spacing: 10) {
      LazyVGrid(columns: columns, spacing: 6) {
        ForEach(Calendar.current.shortWeekdaySymbols, id: \.self) { day in
          Text(String(day.prefix(1)))
            .font(.caption2.weight(.bold))
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity)
        }

        ForEach(cells) { cell in
          MonthCellView(
            cell: cell,
            openDayAction: {
              withAnimation(.snappy(duration: 0.22)) {
                selectedDate = cell.date
                scope = .day
              }
            },
            coverAction: coverAction
          )
        }
      }
    }
    .padding(.vertical, 6)
  }
}

private struct MonthCellView: View {
  let cell: MonthCell
  let openDayAction: () -> Void
  let coverAction: (ScheduleAssignment) -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 3) {
      Button(action: openDayAction) {
        Text(cell.date.formatted(.dateTime.day()))
          .font(.caption2.weight(.bold))
          .foregroundStyle(cell.isCurrentMonth ? .primary : .secondary)
          .frame(maxWidth: .infinity, alignment: .leading)
      }
      .buttonStyle(.plain)

      MonthCellLabel(prefix: "OFF", value: cell.offSummary, tint: ClinicalPalette.teal)
      MonthCallLabel(assignments: Array(cell.assignments.prefix(2)), action: coverAction)
    }
    .padding(.horizontal, 4)
    .padding(.vertical, 5)
    .frame(maxWidth: .infinity, minHeight: 62, alignment: .topLeading)
    .background(cellBackground, in: RoundedRectangle(cornerRadius: 9))
    .overlay {
      RoundedRectangle(cornerRadius: 9)
        .stroke(cell.isToday ? ClinicalPalette.teal.opacity(0.55) : Color.white.opacity(0.58), lineWidth: cell.isToday ? 1.1 : 0.7)
    }
  }

  private var cellBackground: Color {
    if cell.isToday {
      return ClinicalPalette.tealSoft.opacity(0.82)
    }
    if !cell.isCurrentMonth {
      return Color.white.opacity(0.42)
    }
    return ClinicalPalette.card.opacity(0.74)
  }
}

private struct MonthCallLabel: View {
  let assignments: [ScheduleAssignment]
  let action: (ScheduleAssignment) -> Void

  var body: some View {
    if assignments.isEmpty {
      Text(" ")
        .font(.system(size: 9, weight: .semibold, design: .rounded))
        .frame(height: 13)
    } else {
      HStack(spacing: 2) {
        Text("ON")
          .font(.system(size: 9, weight: .semibold, design: .rounded))
          .foregroundStyle(ClinicalPalette.teal)

        ForEach(assignments) { assignment in
          Button {
            action(assignment)
          } label: {
            Text(assignment.surgeon)
              .font(.system(size: 9, weight: .semibold, design: .rounded))
              .foregroundStyle(ClinicalPalette.teal)
              .lineLimit(1)
          }
          .buttonStyle(.plain)
          .disabled(assignment.rotationId == nil)
        }
      }
      .minimumScaleFactor(0.55)
      .padding(.horizontal, 3)
      .padding(.vertical, 2)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(ClinicalPalette.teal.opacity(0.11), in: RoundedRectangle(cornerRadius: 4))
    }
  }
}

private struct MonthCellLabel: View {
  let prefix: String
  let value: String
  let tint: Color

  var body: some View {
    if value.isEmpty {
      Text(" ")
        .font(.system(size: 9, weight: .semibold, design: .rounded))
        .frame(height: 13)
    } else {
      Text("\(prefix) \(value)")
        .font(.system(size: 9, weight: .semibold, design: .rounded))
        .foregroundStyle(tint)
        .lineLimit(1)
        .minimumScaleFactor(0.55)
        .padding(.horizontal, 3)
        .padding(.vertical, 2)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tint.opacity(0.11), in: RoundedRectangle(cornerRadius: 4))
    }
  }
}
