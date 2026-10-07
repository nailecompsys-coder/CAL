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

  private var groups: [ClinicOrFacilityGroup] {
    ClinicOrScheduleBuilder.groups(from: day.mySchedule)
  }

  private var isToday: Bool { Calendar.current.isDateInToday(day.date) }

  var body: some View {
    HStack(alignment: .top, spacing: 12) {
      VStack(spacing: 2) {
        Text(day.date.formatted(.dateTime.weekday(.abbreviated)))
          .font(.caption.weight(.semibold))
          .foregroundStyle(isToday ? ClinicalPalette.teal : .secondary)
        Text(day.date.formatted(.dateTime.day()))
          .font(.title3.weight(.bold))
          .foregroundStyle(isToday ? ClinicalPalette.teal : ClinicalPalette.ink)
      }
      .frame(minWidth: 36)

      VStack(alignment: .leading, spacing: 6) {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
          WeekCallLine(assignments: Array(day.assignments.prefix(3)), action: coverAction)
          if !day.meetings.isEmpty {
            Image(systemName: "person.2.fill")
              .font(.caption)
              .foregroundStyle(ClinicalPalette.meetingStrong)
          }
          Spacer(minLength: 8)
          if !day.off.isEmpty {
            Text("Off  " + day.off.prefix(4).joined(separator: " "))
              .font(.caption)
              .foregroundStyle(.secondary)
              .lineLimit(1)
              .minimumScaleFactor(0.8)
          }
        }

        ForEach(["AM", "PM"], id: \.self) { period in
          let periodGroups = groups.filter { $0.period == period }
          if !periodGroups.isEmpty {
            WeekPeriodLine(period: period, groups: periodGroups)
          }
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    }
    .contentShape(Rectangle())
    .onTapGesture { openDay() }
    .calCard(padding: 12)
    .overlay {
      RoundedRectangle(cornerRadius: 16, style: .continuous)
        .stroke(isToday ? ClinicalPalette.teal : Color.clear, lineWidth: 1.5)
    }
  }

  private func openDay() {
    withAnimation(.easeInOut(duration: 0.2)) {
      selectedDate = day.date
      scope = .day
    }
  }
}

/// "Call  WG LW  ALT JD" — each surgeon still opens the cover sheet.
private struct WeekCallLine: View {
  let assignments: [ScheduleAssignment]
  let action: (ScheduleAssignment) -> Void

  var body: some View {
    HStack(spacing: 8) {
      Text("Call")
        .font(.caption.weight(.semibold))
        .foregroundStyle(ClinicalPalette.teal)
      if assignments.isEmpty {
        Text("—").font(.caption).foregroundStyle(.secondary)
      } else {
        ForEach(assignments) { assignment in
          Button {
            action(assignment)
          } label: {
            HStack(spacing: 3) {
              Text(assignment.locationShort.replacingOccurrences(of: " Group", with: ""))
                .font(.caption2)
                .foregroundStyle(.secondary)
              SmallCoverageInitialsView(assignment: assignment)
            }
          }
          .buttonStyle(.plain)
          .disabled(assignment.rotationId == nil)
        }
      }
    }
  }
}

/// "AM  Winter Garden OR" — OFF with booked work shows its case count in red.
private struct WeekPeriodLine: View {
  let period: String
  let groups: [ClinicOrFacilityGroup]

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 8) {
      Text(period)
        .font(.caption.weight(.bold))
        .foregroundStyle(.secondary)
      Text(groups.map(\.title).joined(separator: " · "))
        .font(.subheadline)
        .foregroundStyle(ClinicalPalette.ink)
        .lineLimit(1)
        .minimumScaleFactor(0.8)
      ForEach(groups.filter { $0.isEmptyCard && !$0.details.isEmpty }) { group in
        Text(group.countLabel)
          .font(.caption.weight(.semibold))
          .foregroundStyle(Color.red)
      }
    }
  }
}

private struct SmallCoverageInitialsView: View {
  let assignment: ScheduleAssignment

  var body: some View {
    VStack(spacing: 1) {
      callInitials
      if assignment.isBackup {
        Text("Backup")
          .font(.caption2.weight(.semibold))
          .foregroundStyle(ClinicalPalette.teal)
      }
    }
  }

  @ViewBuilder private var callInitials: some View {
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
