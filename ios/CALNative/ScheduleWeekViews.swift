import SwiftUI

struct CompactRangeHeader: View {
  let title: String
  let subtitle: String
  let previousAction: () -> Void
  let nextAction: () -> Void

  var body: some View {
    ScheduleDateStepper(
      title: title,
      subtitle: subtitle,
      previousAction: previousAction,
      nextAction: nextAction,
      onTitleTap: nil
    )
  }
}

struct CompactWeekDayCard: View {
  let day: ScheduleDay
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope
  let coverAction: (ScheduleAssignment) -> Void

  private var clinicSummary: String {
    let parts = day.mySchedule.prefix(3).map { item in
      let label = item.title
      if item.period.uppercased() == "AM" || item.period.uppercased() == "PM" {
        return "\(item.period.uppercased()) \(label)"
      }
      return label
    }
    return parts.joined(separator: " · ")
  }

  var body: some View {
    HStack(alignment: .center, spacing: 10) {
      VStack(spacing: 1) {
        Text(day.date.formatted(.dateTime.weekday(.abbreviated)))
          .font(.caption2.weight(.bold))
          .foregroundStyle(.secondary)
        Text(day.date.formatted(.dateTime.day()))
          .font(.subheadline.weight(.bold))
          .foregroundStyle(Calendar.current.isDateInToday(day.date) ? ClinicalPalette.teal : ClinicalPalette.ink)
      }
      .frame(width: 34)

      VStack(alignment: .leading, spacing: 4) {
        HStack(spacing: 8) {
          ScheduleAssignmentActionLine(
            prefix: "ON",
            assignments: Array(day.assignments.prefix(3)),
            tint: ClinicalPalette.teal,
            action: coverAction
          )

          if !day.meetings.isEmpty {
            Image(systemName: "person.2.fill")
              .font(.system(size: 10, weight: .semibold))
              .foregroundStyle(ClinicalPalette.lavender)
          }
        }

        ScheduleStatusLine(
          prefix: "OFF",
          value: day.off.prefix(4).joined(separator: " "),
          tint: ClinicalPalette.scrubInk
        )

        if !clinicSummary.isEmpty {
          ScheduleStatusLine(
            prefix: "OR",
            value: clinicSummary,
            tint: ClinicalPalette.teal
          )
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 8)
    .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
    .contentShape(Rectangle())
    .onTapGesture {
      openDay()
    }
    .liquidGlassCard(
      cornerRadius: 14,
      tint: Calendar.current.isDateInToday(day.date) ? ClinicalPalette.tealSoft : ClinicalPalette.card
    )
  }

  private func openDay() {
    withAnimation(.easeInOut(duration: 0.2)) {
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
        .frame(width: 26, alignment: .leading)

      if assignments.isEmpty {
        Text("—")
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
        .frame(width: 26, alignment: .leading)

      if value.isEmpty {
        Text("—")
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
