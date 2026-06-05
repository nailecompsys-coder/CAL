import SwiftUI

struct DayScheduleSections: View {
  let day: ScheduleDay

  var body: some View {
    Section {
      ScheduleDailyGlanceCard(day: day)
    }
    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 6, trailing: 16))
    .listRowBackground(Color.clear)

    Section("My Schedule") {
      if day.mySchedule.isEmpty {
        Label("No clinic or hospital schedule", systemImage: "checkmark.circle")
          .font(.subheadline)
          .foregroundStyle(.secondary)
      } else {
        ForEach(day.mySchedule) { item in
          MyScheduleRow(item: item)
        }
      }
    }
    .listRowBackground(Color.white.opacity(0.68))

    Section("Meetings") {
      if day.meetings.isEmpty {
        Label("No meetings", systemImage: "checkmark.circle")
          .font(.subheadline)
          .foregroundStyle(.secondary)
      } else {
        ForEach(day.meetings) { meeting in
          MeetingRow(item: meeting)
        }
      }
    }
    .listRowBackground(Color.white.opacity(0.68))

    Section("Personal Items") {
      if day.personalItems.isEmpty {
        Label("No personal items", systemImage: "checkmark.circle")
          .font(.subheadline)
          .foregroundStyle(.secondary)
      } else {
        ForEach(day.personalItems, id: \.self) { item in
          Label(item, systemImage: "note.text")
            .font(.subheadline)
        }
      }
    }
    .listRowBackground(Color.white.opacity(0.68))
  }
}

struct MyScheduleRow: View {
  let item: DoctorScheduleItem

  var body: some View {
    HStack(spacing: 10) {
      Text(item.period)
        .font(.caption2.weight(.bold))
        .foregroundStyle(ClinicalPalette.teal)
        .frame(width: 28, alignment: .leading)

      VStack(alignment: .leading, spacing: 2) {
        Text(item.title)
          .font(.subheadline.weight(.semibold))
        if !item.subtitle.isEmpty {
          Text(item.subtitle)
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      Spacer()

      if !item.timeRange.isEmpty {
        Text(item.timeRange)
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)
      }
    }
    .padding(.vertical, 1)
  }
}

private struct MeetingRow: View {
  let item: DoctorScheduleItem

  var body: some View {
    HStack(spacing: 10) {
      Image(systemName: "person.2.wave.2")
        .font(.caption)
        .foregroundStyle(ClinicalPalette.teal)
        .frame(width: 20)

      VStack(alignment: .leading, spacing: 2) {
        Text(item.title)
          .font(.subheadline.weight(.semibold))
        if !item.subtitle.isEmpty {
          Text(item.subtitle)
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      Spacer()

      if !item.timeRange.isEmpty {
        Text(item.timeRange)
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)
      }
    }
    .padding(.vertical, 1)
  }
}

struct ScheduleDailyGlanceCard: View {
  let day: ScheduleDay
  var coverAction: ((ScheduleAssignment) -> Void)?

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text("On Call")
        .font(.caption.weight(.semibold))
        .foregroundStyle(.secondary)

      if !day.assignments.isEmpty {
        Divider().opacity(0.45)
        VStack(spacing: 8) {
          ForEach(day.assignments) { assignment in
            GlanceOnCallLine(assignment: assignment, coverAction: coverAction)
          }
        }
      } else {
        EmptyDashboardRow(title: "No on-call coverage scheduled")
      }
    }
    .padding(14)
    .liquidGlassCard(cornerRadius: 18, tint: ClinicalPalette.tealSoft)
  }
}

private struct GlanceOnCallLine: View {
  let assignment: ScheduleAssignment
  var coverAction: ((ScheduleAssignment) -> Void)?

  var body: some View {
    Button {
      coverAction?(assignment)
    } label: {
      HStack(spacing: 10) {
        Image(systemName: assignment.systemImage)
          .font(.body)
          .foregroundStyle(ClinicalPalette.teal)
          .frame(width: 22)

        VStack(alignment: .leading, spacing: 2) {
          Text(assignment.locationShort)
            .font(.subheadline.weight(.semibold))
        }

        Spacer()

        CoverageInitialsView(assignment: assignment)

        if assignment.rotationId != nil {
          Image(systemName: "chevron.right")
            .font(.caption2.weight(.bold))
            .foregroundStyle(.tertiary)
        }
      }
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .disabled(coverAction == nil || assignment.rotationId == nil)
  }
}

private struct CoverageInitialsView: View {
  let assignment: ScheduleAssignment

  var body: some View {
    if assignment.isCovered {
      HStack(spacing: 5) {
        StruckInitialsText(
          text: assignment.originalInitials,
          font: .system(.body, design: .monospaced).weight(.semibold)
        )

        Text(assignment.coveringInitials ?? assignment.surgeon)
          .font(.system(.body, design: .monospaced).weight(.semibold))
          .foregroundStyle(.primary)
      }
    } else {
      Text(assignment.surgeon)
        .font(.system(.body, design: .monospaced).weight(.semibold))
        .foregroundStyle(.primary)
    }
  }
}

struct FlowLine: View {
  let items: [String]

  var body: some View {
    HStack(spacing: 5) {
      ForEach(items, id: \.self) { item in
        Text(item)
          .font(.caption2.weight(.semibold))
          .padding(.horizontal, 8)
          .padding(.vertical, 4)
          .background(ClinicalPalette.porcelainChip.opacity(0.94), in: Capsule())
          .overlay {
            Capsule()
              .stroke(ClinicalPalette.scrubInk.opacity(0.26), lineWidth: 0.75)
          }
          .foregroundStyle(ClinicalPalette.scrubInk)
      }
    }
  }
}
