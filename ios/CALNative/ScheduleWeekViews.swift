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
    let parts = ClinicOrScheduleBuilder.groups(from: day.mySchedule).prefix(3).map { group in
      if group.timeRange.isEmpty {
        return group.title
      }
      return "\(group.timeRange) \(group.title)"
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
        HStack(alignment: .center, spacing: 8) {
          ScheduleAssignmentActionLine(
            prefix: "ON",
            assignments: Array(day.assignments.prefix(3)),
            tint: ClinicalPalette.teal,
            action: coverAction
          )

          if !day.meetings.isEmpty {
            Image(systemName: "person.2.fill")
              .font(ClinicalTypography.captionEmphasized)
              .foregroundStyle(ClinicalPalette.lavender)
          }

          Spacer(minLength: 8)

          ScheduleStatusLine(
            prefix: "OFF",
            value: day.off.prefix(4).joined(separator: " "),
            tint: ClinicalPalette.scrubInk,
            alignment: .trailing
          )
        }

        if !clinicSummary.isEmpty {
          ScheduleStatusLine(
            prefix: "OR/CL",
            value: clinicSummary,
            tint: ClinicalPalette.teal,
            alignment: .leading
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
  }
}

private struct SmallCoverageInitialsView: View {
  let assignment: ScheduleAssignment

  var body: some View {
    if assignment.isCovered {
      HStack(spacing: 2) {
        StruckInitialsText(
          text: assignment.originalInitials,
          font: ClinicalTypography.monoChip
        )
        Text(assignment.coveringInitials ?? assignment.surgeon)
          .font(ClinicalTypography.monoChip)
          .foregroundStyle(.primary)
      }
      .padding(.horizontal, 3)
      .padding(.vertical, 1)
      .background(ClinicalPalette.teal.opacity(0.08), in: Capsule())
    } else {
      Text(assignment.surgeon)
        .font(ClinicalTypography.monoChip)
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
  var alignment: HorizontalAlignment = .leading

  private var isTrailing: Bool { alignment == .trailing }

  var body: some View {
    HStack(spacing: 6) {
      if isTrailing {
        Spacer(minLength: 0)
      }

      Text(prefix)
        .font(ClinicalTypography.badge)
        .foregroundStyle(tint)
        .frame(width: isTrailing ? nil : (prefix.count > 3 ? 40 : 26), alignment: .leading)

      if value.isEmpty {
        Text("—")
          .font(.caption.weight(.medium))
          .foregroundStyle(.secondary)
      } else {
        Text(value)
          .font(ClinicalTypography.caption)
          .foregroundStyle(.primary)
          .lineLimit(1)
          .minimumScaleFactor(0.72)
          .multilineTextAlignment(isTrailing ? .trailing : .leading)
      }
    }
    .frame(maxWidth: isTrailing ? nil : .infinity, alignment: isTrailing ? .trailing : .leading)
  }
}
