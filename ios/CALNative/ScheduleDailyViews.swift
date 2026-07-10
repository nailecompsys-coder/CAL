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
  var openPatientsAction: (() -> Void)?

  private var accent: Color {
    if item.isBlockOr {
      return ClinicalPalette.blockStrong
    }
    return ClinicalPalette.amber
  }

  var body: some View {
    Button {
      openPatientsAction?()
    } label: {
      HStack(spacing: 10) {
        RoundedRectangle(cornerRadius: 2, style: .continuous)
          .fill(accent)
          .frame(width: 4, height: 28)

        Text(item.period)
          .font(.caption2.weight(.bold))
          .foregroundStyle(accent)
          .frame(width: 28, alignment: .leading)

        VStack(alignment: .leading, spacing: 2) {
          Text(item.title)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(ClinicalPalette.ink)
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

        if openPatientsAction != nil {
          Image(systemName: "chevron.right")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(ClinicalPalette.teal.opacity(0.7))
        }
      }
      .padding(.vertical, 1)
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .disabled(openPatientsAction == nil)
  }
}

private struct MeetingRow: View {
  let item: DoctorScheduleItem

  var body: some View {
    HStack(spacing: 10) {
      RoundedRectangle(cornerRadius: 2, style: .continuous)
        .fill(ClinicalPalette.meetingStrong)
        .frame(width: 4, height: 28)

      Image(systemName: "person.2.wave.2")
        .font(.caption)
        .foregroundStyle(ClinicalPalette.meetingStrong)
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
    HStack(alignment: .top, spacing: 8) {
      VStack(alignment: .leading, spacing: 6) {
        Text("On Call")
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)

        if day.assignments.isEmpty {
          Text("None")
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
        } else {
          VStack(alignment: .leading, spacing: 4) {
            ForEach(day.assignments.prefix(3)) { assignment in
              GlanceOnCallLine(assignment: assignment, coverAction: coverAction)
            }
          }
        }
      }
      .padding(10)
      .frame(maxWidth: .infinity, minHeight: 72, alignment: .topLeading)
      .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.tealSoft)

      VStack(alignment: .leading, spacing: 6) {
        Text("Off")
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)

        if day.off.isEmpty {
          Text("None")
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
        } else {
          FlowLine(items: Array(day.off.prefix(8)))
            .frame(maxWidth: .infinity, alignment: .leading)
        }
      }
      .padding(10)
      .frame(maxWidth: .infinity, minHeight: 72, alignment: .topLeading)
      .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.scrub)
    }
  }
}

private struct GlanceOnCallLine: View {
  let assignment: ScheduleAssignment
  var coverAction: ((ScheduleAssignment) -> Void)?

  var body: some View {
    Button {
      coverAction?(assignment)
    } label: {
      HStack(spacing: 6) {
        Text(assignment.locationShort)
          .font(.caption.weight(.semibold))
          .foregroundStyle(ClinicalPalette.ink)
          .lineLimit(1)

        Spacer(minLength: 2)

        CoverageInitialsView(assignment: assignment)

        if assignment.rotationId != nil {
          Image(systemName: "chevron.right")
            .font(.system(size: 9, weight: .bold))
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
      HStack(spacing: 3) {
        StruckInitialsText(
          text: assignment.originalInitials,
          font: .system(.caption, design: .monospaced).weight(.semibold)
        )

        Text(assignment.coveringInitials ?? assignment.surgeon)
          .font(.system(.caption, design: .monospaced).weight(.semibold))
          .foregroundStyle(.primary)
      }
    } else {
      Text(assignment.surgeon)
        .font(.system(.caption, design: .monospaced).weight(.semibold))
        .foregroundStyle(.primary)
    }
  }
}

struct FlowLine: View {
  let items: [String]

  var body: some View {
    // Wrap-friendly flow using flexible layout
    FlexibleInitialsWrap(items: items)
  }
}

private struct FlexibleInitialsWrap: View {
  let items: [String]

  var body: some View {
    VStack(alignment: .leading, spacing: 4) {
      ForEach(chunked(items, size: 4), id: \.self) { row in
        HStack(spacing: 4) {
          ForEach(row, id: \.self) { item in
            Text(item)
              .font(.caption2.weight(.semibold))
              .padding(.horizontal, 6)
              .padding(.vertical, 3)
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
  }

  private func chunked(_ values: [String], size: Int) -> [[String]] {
    guard size > 0 else { return [values] }
    var rows: [[String]] = []
    var index = 0
    while index < values.count {
      let end = min(index + size, values.count)
      rows.append(Array(values[index..<end]))
      index = end
    }
    return rows
  }
}
