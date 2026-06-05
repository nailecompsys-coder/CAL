import SwiftUI

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
