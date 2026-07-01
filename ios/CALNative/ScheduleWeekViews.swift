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
