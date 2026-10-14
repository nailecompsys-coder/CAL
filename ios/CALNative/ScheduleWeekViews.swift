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
        WeekCallOffRow(
          assignments: Array(day.assignments.prefix(3)),
          offInitials: Array(day.off.prefix(4)),
          coverAction: coverAction
        )

        ForEach(["AM", "PM"], id: \.self) { period in
          let periodGroups = groups.filter { $0.period == period }
          if let primary = Self.primaryScheduleGroup(from: periodGroups) {
            WeekPeriodLine(period: period, groups: [primary])
            ForEach(periodGroups.filter { $0.id != primary.id }) { extra in
              WeekSecondaryLine(title: extra.title)
            }
          }
        }

        ForEach(day.meetings) { meeting in
          WeekMeetingLine(item: meeting)
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

  /// Master / clinic card first (NA/OFF preferred when present); extras stay on their own lines.
  private static func primaryScheduleGroup(from groups: [ClinicOrFacilityGroup]) -> ClinicOrFacilityGroup? {
    groups.first(where: \.isEmptyCard) ?? groups.first
  }
}

/// Call + Off share one row when width allows; Off drops under Call on narrow phones.
private struct WeekCallOffRow: View {
  let assignments: [ScheduleAssignment]
  let offInitials: [String]
  let coverAction: (ScheduleAssignment) -> Void

  var body: some View {
    if #available(iOS 16.0, *) {
      ViewThatFits(in: .horizontal) {
        sideBySideRow
        stackedRow
      }
    } else {
      // Narrow phones: keep Call intact; Off on the next line.
      stackedRow
    }
  }

  private var sideBySideRow: some View {
    HStack(alignment: .firstTextBaseline, spacing: 8) {
      WeekCallLine(assignments: assignments, action: coverAction)
      Spacer(minLength: 8)
      if !offInitials.isEmpty {
        WeekOffLine(initials: offInitials)
      }
    }
  }

  private var stackedRow: some View {
    VStack(alignment: .leading, spacing: 4) {
      HStack(alignment: .firstTextBaseline, spacing: 8) {
        WeekCallLine(assignments: assignments, action: coverAction)
        Spacer(minLength: 0)
      }
      if !offInitials.isEmpty {
        WeekOffLine(initials: offInitials)
      }
    }
  }
}

private struct WeekOffLine: View {
  let initials: [String]

  var body: some View {
    Text("Off  " + initials.joined(separator: " "))
      .font(.caption)
      .foregroundStyle(.secondary)
      .lineLimit(1)
      .minimumScaleFactor(0.7)
  }
}

/// "Call  WG LW  ALT JD" — each surgeon still opens the cover sheet.
private struct WeekCallLine: View {
  let assignments: [ScheduleAssignment]
  let action: (ScheduleAssignment) -> Void

  var body: some View {
    HStack(spacing: 6) {
      Text("Call")
        .font(.caption.weight(.semibold))
        .foregroundStyle(ClinicalPalette.teal)
        .lineLimit(1)
        .layoutPriority(1)
      if assignments.isEmpty {
        Text("—")
          .font(.caption)
          .foregroundStyle(.secondary)
          .lineLimit(1)
      } else {
        ForEach(assignments) { assignment in
          Button {
            action(assignment)
          } label: {
            HStack(spacing: 3) {
              Text(assignment.locationShort.replacingOccurrences(of: " Group", with: ""))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
              SmallCoverageInitialsView(assignment: assignment)
            }
          }
          .buttonStyle(.plain)
          .disabled(assignment.rotationId == nil)
          .layoutPriority(1)
        }
      }
    }
    .lineLimit(1)
    .minimumScaleFactor(0.7)
  }
}

/// "AM  Winter Garden OR" — OFF with booked work shows its case count in red.
private struct WeekPeriodLine: View {
  let period: String
  let groups: [ClinicOrFacilityGroup]
  @ScaledMetric(relativeTo: .footnote) private var labelColumn: CGFloat = 36

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 8) {
      Text(period)
        .font(.caption.weight(.bold))
        .foregroundStyle(.secondary)
        .frame(width: labelColumn, alignment: .leading)
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

/// Extra facility / address under AM or PM — never mashed onto the period title.
private struct WeekSecondaryLine: View {
  let title: String
  @ScaledMetric(relativeTo: .footnote) private var labelColumn: CGFloat = 36

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 8) {
      Color.clear
        .frame(width: labelColumn, height: 1)
      Text(title)
        .font(.subheadline)
        .foregroundStyle(ClinicalPalette.ink)
        .lineLimit(2)
        .minimumScaleFactor(0.85)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
  }
}

/// Meeting on its own row — title + place, never appended to PM.
private struct WeekMeetingLine: View {
  let item: DoctorScheduleItem
  @ScaledMetric(relativeTo: .footnote) private var labelColumn: CGFloat = 36

  private var place: String {
    [item.location, item.room, item.procedure]
      .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
      .filter { !$0.isEmpty }
      .joined(separator: " · ")
  }

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 8) {
      Text("Mtg")
        .font(.caption.weight(.bold))
        .foregroundStyle(ClinicalPalette.meetingStrong)
        .frame(width: labelColumn, alignment: .leading)
      VStack(alignment: .leading, spacing: 2) {
        Text(item.title)
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(ClinicalPalette.meetingStrong)
          .lineLimit(2)
        if !place.isEmpty, place.caseInsensitiveCompare(item.title) != .orderedSame {
          Text(place)
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(2)
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)
      if !item.timeRange.isEmpty {
        Text(item.timeRange)
          .font(.caption2)
          .foregroundStyle(.secondary)
          .lineLimit(1)
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
          .lineLimit(1)
          .minimumScaleFactor(0.7)
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
          .lineLimit(1)
          .minimumScaleFactor(0.7)
      }
      .lineLimit(1)
      .minimumScaleFactor(0.7)
      .padding(.horizontal, 3)
      .padding(.vertical, 1)
      .background(ClinicalPalette.teal.opacity(0.08), in: Capsule())
    } else {
      Text(assignment.surgeon)
        .font(ClinicalTypography.monoChip)
        .foregroundStyle(.primary)
        .lineLimit(1)
        .minimumScaleFactor(0.7)
        .padding(.horizontal, 4)
        .padding(.vertical, 1)
        .background(ClinicalPalette.teal.opacity(0.08), in: Capsule())
    }
  }
}
