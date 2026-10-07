import SwiftUI

struct DayScheduleSections: View {
  let day: ScheduleDay

  var body: some View {
    Section {
      ScheduleDailyGlanceCard(day: day)
    }
    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 6, trailing: 16))
    .listRowBackground(Color.clear)

    Section("Clinic / OR Schedule") {
      ClinicOrScheduleList(dayId: day.id, items: day.mySchedule)
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
        ForEach(day.personalItems) { item in
          Label(item.displayTitle, systemImage: "note.text")
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

  var body: some View {
    Button {
      openPatientsAction?()
    } label: {
      HStack(alignment: .top, spacing: 10) {
        Text(item.timeRange.isEmpty ? "—" : item.timeRange)
          .font(ClinicalTypography.monoCaption)
          .foregroundStyle(ClinicalPalette.ink)
          .frame(width: 96, alignment: .leading)

        VStack(alignment: .leading, spacing: 2) {
          Text(item.title)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(ClinicalPalette.ink)
          if !item.subtitle.isEmpty {
            Text(item.subtitle)
              .font(.caption2)
              .foregroundStyle(ClinicalPalette.muted)
              .lineLimit(1)
          }
        }

        Spacer(minLength: 0)

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
    VStack(alignment: .leading, spacing: 3) {
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
              .font(ClinicalTypography.badge)
              .foregroundStyle(.tertiary)
          }
        }
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .disabled(coverAction == nil || assignment.rotationId == nil)

      if assignment.isBackup {
        Text("Backup")
          .font(.caption.weight(.semibold))
          .foregroundStyle(ClinicalPalette.teal)
      }
    }
  }
}

private struct CoverageInitialsView: View {
  let assignment: ScheduleAssignment

  var body: some View {
    if assignment.isCovered {
      HStack(spacing: 3) {
        StruckInitialsText(
          text: assignment.originalInitials,
          font: ClinicalTypography.monoChip
        )

        Text(assignment.coveringInitials ?? assignment.surgeon)
          .font(ClinicalTypography.monoChip)
          .foregroundStyle(.primary)
      }
    } else {
      Text(assignment.surgeon)
        .font(ClinicalTypography.monoChip)
        .foregroundStyle(.primary)
    }
  }
}

struct FlowLine: View {
  let items: [String]

  var body: some View {
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
              .font(ClinicalTypography.captionEmphasized)
              .lineLimit(1)
              .fixedSize(horizontal: true, vertical: false)
              .frame(minWidth: 20, minHeight: 20)
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

/// Tap a date: every surgeon and PA, AM and PM, by geographic block group. Locations only.
struct WhosWhereView: View {
  @ObservedObject var store: NativeScheduleStore
  @State var day: Date
  @Environment(\.dismiss) private var dismiss
  @State private var rows: [NativeWhosWhereRow] = []
  @State private var selectedGroupId = 0
  @State private var isLoading = false
  @State private var errorMessage: String?

  private var groups: [(id: Int, label: String)] {
    var seen = Set<Int>()
    var out: [(id: Int, label: String)] = []
    for row in rows {
      guard let id = row.groupId, seen.insert(id).inserted else { continue }
      out.append((id: id, label: Self.shortGroupName(row.group)))
    }
    return out.sorted { $0.id < $1.id }
  }

  var body: some View {
    CalNavigation {
      List {
        Section {
          WhosWhereDayStepper(day: $day)
          Picker("Group", selection: $selectedGroupId) {
            ForEach(groups, id: \.id) { group in
              Text(group.label).tag(group.id)
            }
          }
          .pickerStyle(.segmented)
        }

        if let errorMessage {
          Section {
            Label(errorMessage, systemImage: "exclamationmark.triangle")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
        } else if isLoading && rows.isEmpty {
          Section { ProgressView() }
        } else {
          groupSections(selectedGroupId)
        }
      }
      .navigationTitle("Who's where")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .confirmationAction) {
          Button("Done") { dismiss() }
        }
      }
      .task(id: day) { await load() }
    }
  }

  @ViewBuilder
  private func groupSections(_ groupId: Int) -> some View {
    let onCall = rows.filter { $0.session == "call" && $0.groupId == groupId }
    let people = WhosWherePerson.people(in: groupId, from: rows)
    if !onCall.isEmpty {
      Section("On call") {
        ForEach(onCall) { row in
          Text(row.name).font(ClinicalTypography.rowTitle)
        }
      }
    }
    Section {
      WhosWhereTableHeader()
      ForEach(people.filter { !$0.isPA }) { WhosWhereTableRow(person: $0) }
      let pas = people.filter(\.isPA)
      if !pas.isEmpty {
        Text("PAs")
          .font(ClinicalTypography.sectionLabel)
          .foregroundStyle(ClinicalPalette.muted)
        ForEach(pas) { WhosWhereTableRow(person: $0) }
      }
    }
  }

  private func load() async {
    isLoading = true
    defer { isLoading = false }
    do {
      rows = try await store.fetchWhosWhere(day: day)
      errorMessage = nil
      if !groups.contains(where: { $0.id == selectedGroupId }) {
        selectedGroupId = groups.first?.id ?? 0
      }
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  static func shortGroupName(_ group: String) -> String {
    let upper = group.uppercased()
    if upper.contains("WINTER") || upper.contains("APOPKA") || upper.contains("MINNEOLA") {
      return "WG Group"
    }
    if upper.contains("ALTAMONTE") {
      return "ALT Group"
    }
    return group
  }
}

/// One person's AM and PM half-days, shown in a group when either half-day is there,
/// they are on call there, or they have no location at all that day.
private struct WhosWherePerson: Identifiable {
  let id: Int
  let lastName: String
  let isPA: Bool
  let am: NativeWhosWhereRow?
  let pm: NativeWhosWhereRow?
  let isOnCall: Bool
  let noCall: Bool

  static func people(in groupId: Int, from rows: [NativeWhosWhereRow]) -> [WhosWherePerson] {
    let halfDays = rows.filter { $0.session != "call" }
    let onCallIds = Set(rows.filter { $0.session == "call" && $0.groupId == groupId }.map(\.surgeonId))
    var order: [Int] = []
    for row in halfDays where !order.contains(row.surgeonId) {
      order.append(row.surgeonId)
    }
    return order.compactMap { id in
      let mine = halfDays.filter { $0.surgeonId == id }
      let am = mine.first { $0.session == "am" }
      let pm = mine.first { $0.session == "pm" }
      let groupIds = Set(mine.compactMap(\.groupId))
      guard groupIds.contains(groupId) || groupIds.isEmpty || onCallIds.contains(id),
            let any = am ?? pm else { return nil }
      return WhosWherePerson(
        id: id,
        lastName: any.name.split(separator: " ").last.map(String.init) ?? any.name,
        isPA: any.isPA,
        am: am,
        pm: pm,
        isOnCall: onCallIds.contains(id),
        noCall: mine.contains(where: \.noCall)
      )
    }
  }
}

private struct WhosWhereTableHeader: View {
  var body: some View {
    HStack(spacing: 8) {
      Text("Surgeon").frame(maxWidth: .infinity, alignment: .leading)
      HStack(spacing: 8) {
        Text("AM").frame(maxWidth: .infinity, alignment: .leading)
        Text("PM").frame(maxWidth: .infinity, alignment: .leading)
      }
      .frame(maxWidth: .infinity)
    }
    .font(ClinicalTypography.caption)
    .foregroundStyle(ClinicalPalette.muted)
  }
}

private struct WhosWhereTableRow: View {
  let person: WhosWherePerson

  var body: some View {
    HStack(spacing: 8) {
      HStack(spacing: 6) {
        Text(person.lastName)
          .font(ClinicalTypography.rowTitle)
          .foregroundStyle(ClinicalPalette.ink)
          .lineLimit(1)
        if person.isOnCall { StatusTag(text: "Call", tint: ClinicalPalette.teal) }
        if person.noCall { StatusTag(text: "No Call") }
      }
      .frame(maxWidth: .infinity, alignment: .leading)
      HStack(spacing: 8) {
        WhosWhereCell(row: person.am).frame(maxWidth: .infinity, alignment: .leading)
        WhosWhereCell(row: person.pm).frame(maxWidth: .infinity, alignment: .leading)
      }
      .frame(maxWidth: .infinity)
    }
  }
}

private struct WhosWhereCell: View {
  let row: NativeWhosWhereRow?

  var body: some View {
    if let row {
      if row.onLeave || row.state == "off" {
        StatusTag(text: "Off")
      } else if !row.location.isEmpty {
        LocationChip(code: row.location)
      } else {
        StatusTag(text: "Open")
      }
    } else {
      StatusTag(text: "Open")
    }
  }
}

private struct WhosWhereDayStepper: View {
  @Binding var day: Date

  var body: some View {
    HStack {
      Button { step(-1) } label: { Image(systemName: "chevron.left") }
      Spacer()
      Text(day.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()))
        .font(ClinicalTypography.rowTitle)
      Spacer()
      Button { step(1) } label: { Image(systemName: "chevron.right") }
    }
    .buttonStyle(.borderless)
  }

  private func step(_ days: Int) {
    day = Calendar.current.date(byAdding: .day, value: days, to: day) ?? day
  }
}
