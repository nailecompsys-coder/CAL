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
  @State private var selectedTab = ""
  @State private var isLoading = false
  @State private var errorMessage: String?

  private static let openTab = "open"

  private var groupTabs: [(key: String, label: String)] {
    var seen = Set<Int>()
    var tabs: [(key: String, label: String)] = []
    for row in rows where row.session != "call" {
      guard let id = row.groupId, !seen.contains(id) else { continue }
      seen.insert(id)
      tabs.append((key: String(id), label: Self.shortGroupName(row.group)))
    }
    tabs.append((key: Self.openTab, label: "Open / Off"))
    return tabs
  }

  var body: some View {
    CalNavigation {
      List {
        Section {
          WhosWhereDayStepper(day: $day)
          Picker("Group", selection: $selectedTab) {
            ForEach(groupTabs, id: \.key) { tab in
              Text(tab.label).tag(tab.key)
            }
          }
          .pickerStyle(.segmented)
        } footer: {
          Text("Locations and sessions only. No patient details.")
        }

        if let errorMessage {
          Section {
            Label(errorMessage, systemImage: "exclamationmark.triangle")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
        } else if isLoading && rows.isEmpty {
          Section { ProgressView() }
        } else if selectedTab == Self.openTab {
          openSections
        } else if let groupId = Int(selectedTab) {
          groupSections(groupId)
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
    if !onCall.isEmpty {
      Section("On call") {
        ForEach(onCall) { row in
          Text(row.name).font(ClinicalTypography.rowTitle)
        }
      }
    }
    ForEach(["am", "pm"], id: \.self) { session in
      let sessionRows = rows.filter { $0.session == session && $0.groupId == groupId }
      WhosWhereSessionSection(session: session, rows: sessionRows, onCallIds: Set(onCall.map(\.surgeonId)))
    }
  }

  @ViewBuilder
  private var openSections: some View {
    ForEach(["am", "pm"], id: \.self) { session in
      let open = rows.filter { $0.session == session && $0.groupId == nil && $0.state == "na" && !$0.onLeave }
      WhosWhereSessionSection(session: session, rows: open, onCallIds: [], title: "\(session.uppercased()) · Open (NA)")
    }
    let off = rows.filter { $0.session != "call" && ($0.state == "off" || $0.onLeave) }
    WhosWhereSessionSection(session: "off", rows: off, onCallIds: [], title: "Off")
  }

  private func load() async {
    isLoading = true
    defer { isLoading = false }
    do {
      rows = try await store.fetchWhosWhere(day: day)
      errorMessage = nil
      if !groupTabs.contains(where: { $0.key == selectedTab }) {
        selectedTab = groupTabs.first?.key ?? Self.openTab
      }
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  static func shortGroupName(_ group: String) -> String {
    let upper = group.uppercased()
    if upper.contains("WINTER") || upper.contains("APOPKA") || upper.contains("MINNEOLA") {
      return "WG / AP / MN"
    }
    if upper.contains("ALTAMONTE") {
      return "Altamonte"
    }
    return group
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

private struct WhosWhereSessionSection: View {
  let session: String
  let rows: [NativeWhosWhereRow]
  let onCallIds: Set<Int>
  var title: String?

  var body: some View {
    Section(title ?? session.uppercased()) {
      if rows.isEmpty {
        EmptyDashboardRow(title: "No one")
      } else {
        let surgeons = rows.filter { !$0.isPA }
        let pas = rows.filter(\.isPA)
        if !surgeons.isEmpty {
          WhosWhereSubheader(text: "Surgeons")
          ForEach(surgeons) { WhosWhereRowView(row: $0, isOnCall: onCallIds.contains($0.surgeonId), showsSession: session == "off") }
        }
        if !pas.isEmpty {
          WhosWhereSubheader(text: "PAs")
          ForEach(pas) { WhosWhereRowView(row: $0, isOnCall: onCallIds.contains($0.surgeonId), showsSession: session == "off") }
        }
      }
    }
  }
}

private struct WhosWhereSubheader: View {
  let text: String

  var body: some View {
    Text(text)
      .font(ClinicalTypography.sectionLabel)
      .foregroundStyle(ClinicalPalette.muted)
  }
}

private struct WhosWhereRowView: View {
  let row: NativeWhosWhereRow
  let isOnCall: Bool
  var showsSession = false

  var body: some View {
    HStack(spacing: 8) {
      Text(row.name)
        .font(ClinicalTypography.rowTitle)
        .foregroundStyle(row.onLeave ? ClinicalPalette.muted : ClinicalPalette.ink)
        .lineLimit(1)
      if showsSession {
        StatusTag(text: row.session.uppercased())
      }
      Spacer(minLength: 4)
      if isOnCall { StatusTag(text: "Call", tint: ClinicalPalette.teal) }
      if row.noCall { StatusTag(text: "No Call") }
      if row.onLeave || row.state == "off" { StatusTag(text: "Off") }
      if !row.location.isEmpty {
        LocationChip(code: row.location)
          .opacity(row.onLeave ? 0.45 : 1)
      } else if row.state == "na" && !row.onLeave {
        StatusTag(text: "NA")
      }
    }
  }
}
