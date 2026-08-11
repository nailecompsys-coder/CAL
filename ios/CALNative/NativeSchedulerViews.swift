import SwiftUI

struct NativeSchedulerShell: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var selectedDate = Date()
  @State private var scope: SchedulerBrowseScope = .week
  @State private var selectedBlock: NativeSchedulerBlock?
  @State private var showCreateBlock = false
  @State private var showChanges = false
  @State private var showJumpMenu = false

  private enum SchedulerBrowseScope {
    case week
    case day
  }

  /// US work week for scheduler: Monday–Sunday (not locale Sunday–Saturday).
  private var calendar: Calendar {
    ClinicalCalendar.mondayFirst
  }

  private var weekStart: Date {
    let interval = calendar.dateInterval(of: .weekOfYear, for: selectedDate)
    return interval?.start ?? calendar.startOfDay(for: selectedDate)
  }

  private var weekEnd: Date {
    calendar.date(byAdding: .day, value: 6, to: weekStart) ?? weekStart
  }

  private var weekDates: [Date] {
    (0..<7).compactMap { offset in
      calendar.date(byAdding: .day, value: offset, to: weekStart)
    }
  }

  private var weekDaySummaries: [SchedulerWeekDaySummary] {
    weekDates.map { date in
      SchedulerWeekDaySummary(date: date, blocks: blocks(on: date))
    }
  }

  private var dayBlockGroups: [SchedulerBlockGroup] {
    groupedBlocks(blocks(on: selectedDate))
  }

  private var stepperTitle: String {
    switch scope {
    case .week:
      return "\(weekStart.formatted(.dateTime.month(.abbreviated).day())) – \(weekEnd.formatted(.dateTime.month(.abbreviated).day()))"
    case .day:
      if calendar.isDateInToday(selectedDate) {
        return "Today · \(selectedDate.formatted(.dateTime.month(.abbreviated).day()))"
      }
      return selectedDate.formatted(.dateTime.weekday(.wide).month(.abbreviated).day())
    }
  }

  private var stepperSubtitle: String {
    switch scope {
    case .week: return "Week"
    case .day: return selectedDate.formatted(.dateTime.year())
    }
  }

  private var isOnCurrentRange: Bool {
    let today = Date()
    switch scope {
    case .week:
      return weekDates.contains { calendar.isDate($0, inSameDayAs: today) }
    case .day:
      return calendar.isDateInToday(selectedDate)
    }
  }

  private var displayWarning: String? {
    Self.friendlyWarning(store.warningMessage)
  }

  var body: some View {
    CalNavigation {
      ZStack {
        ScheduleWaterBackground()
        VStack(spacing: 0) {
          ScheduleDateStepper(
            title: stepperTitle,
            subtitle: stepperSubtitle,
            previousAction: { step(-1) },
            nextAction: { step(1) },
            onTitleTap: { showJumpMenu = true },
            todayAction: { jumpToThisWeek() },
            showsTodayButton: !isOnCurrentRange
          )
          .padding(.horizontal, 16)
          .padding(.top, 10)
          .padding(.bottom, 8)
          .calReadableColumn(ClinicalLayout.wideColumn)

          if scope == .week {
            SchedulerWeekView(
              days: weekDaySummaries,
              statusMessage: displayWarning,
              selectDay: { date in
                withAnimation(.easeInOut(duration: 0.2)) {
                  selectedDate = date
                  scope = .day
                }
              },
              addBlock: { showCreateBlock = true }
            )
            .calReadableColumn(ClinicalLayout.contentColumn)
          } else {
            SchedulerDayDetailView(
              blockGroups: dayBlockGroups,
              statusMessage: displayWarning,
              backToWeek: {
                withAnimation(.easeInOut(duration: 0.2)) {
                  scope = .week
                }
              },
              selectBlock: { block in
                selectedBlock = block
                Task { await store.loadSchedulerBlock(block) }
              },
              addBlock: { showCreateBlock = true }
            )
            .calReadableColumn(ClinicalLayout.contentColumn)
          }
        }
      }
      .navigationTitle("Scheduler")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .principal) {
          if store.canSwitchModes {
            Menu {
              Button {
                Task { await store.switchSessionRole(to: .surgeon) }
              } label: {
                Label("Switch to Schedule", systemImage: "calendar")
              }
              Button(role: .destructive) {
                store.logout()
              } label: {
                Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
              }
            } label: {
              HStack(spacing: 4) {
                Text("Scheduler")
                  .font(ClinicalTypography.headline)
                Image(systemName: "chevron.down")
                  .font(ClinicalTypography.badge)
              }
              .foregroundStyle(.primary)
            }
          } else {
            Text("Scheduler")
              .font(ClinicalTypography.headline)
          }
        }
        ToolbarItemGroup(placement: .navigationBarTrailing) {
          Button {
            showCreateBlock = true
          } label: {
            Label("Add block", systemImage: "plus")
          }
          Button {
            showChanges = true
          } label: {
            Image(systemName: "clock.arrow.circlepath")
          }
          .accessibilityLabel("Recent changes")
          Button {
            Task { await store.loadScheduler(containing: weekStart) }
          } label: {
            Image(systemName: "arrow.clockwise")
          }
          .accessibilityLabel("Refresh")
          if !store.canSwitchModes {
            Button(role: .destructive) {
              store.logout()
            } label: {
              Image(systemName: "rectangle.portrait.and.arrow.right")
            }
            .accessibilityLabel("Sign out")
          }
        }
      }
      .confirmationDialog("Jump", isPresented: $showJumpMenu, titleVisibility: .visible) {
        Button("This week") { jumpToThisWeek() }
        Button("Next month") { jumpToNextMonth() }
        Button("Cancel", role: .cancel) {}
      }
      .sheet(isPresented: $showChanges) {
        CalNavigation {
          SchedulerChangesView(changes: store.schedulerChanges)
            .navigationTitle("Recent")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
              ToolbarItem(placement: .cancellationAction) {
                Button("Done") { showChanges = false }
              }
            }
        }
      }
      .sheet(item: $selectedBlock) { block in
        assignSheet(for: block)
      }
      .sheet(isPresented: $showCreateBlock) {
        SchedulerCreateBlockSheet(
          initialDate: selectedDate,
          loadMeta: { try await store.loadSchedulerMeta() },
          createAction: { date, locationId, session, startTime, endTime, notes in
            _ = try await store.createSchedulerBlock(
              date: date,
              locationId: locationId,
              session: session,
              startTime: startTime,
              endTime: endTime,
              notes: notes
            )
            // Stay on week (or day if already drilled in); do not auto-open Assign.
            selectedDate = date
          }
        )
      }
    }
    .task {
      await store.loadScheduler(containing: weekStart)
    }
    .onChange(of: selectedDate) { newValue in
      Task { await store.loadScheduler(containing: newValue) }
    }
  }

  @ViewBuilder
  private func assignSheet(for block: NativeSchedulerBlock) -> some View {
    SchedulerAssignSheet(
      block: block,
      detail: store.selectedSchedulerDetail,
      dayBlocks: store.schedulerBlocks.filter { $0.date == block.date },
      loadBlocksOnDate: { date in
        try await store.fetchSchedulerBlocks(on: date)
      },
      createBlockOnDate: { date in
        try await store.createSchedulerBlock(
          date: date,
          locationId: block.locationId,
          session: block.session.isEmpty ? "custom" : block.session,
          startTime: block.start,
          endTime: block.end,
          notes: "Created while rescheduling a case"
        )
      },
      isLoading: store.isLoading,
      assignAction: { surgeon, startTime, caseCount, note in
        do {
          _ = try await store.assignSchedulerBlock(
            blockId: block.id,
            surgeonId: surgeon.surgeonId,
            startTime: startTime,
            caseCount: caseCount,
            note: note
          )
        } catch {
          store.setWarningMessage(Self.friendlyWarning(error.localizedDescription) ?? "Couldn't update assignment.")
        }
      },
      addCaseAction: { surgeonId, startTime, procedure, patientName in
        do {
          try await store.addSchedulerCase(
            blockId: block.id,
            surgeonId: surgeonId,
            startTime: startTime,
            procedure: procedure,
            patientName: patientName
          )
        } catch {
          store.setWarningMessage(Self.friendlyWarning(error.localizedDescription) ?? "Couldn't add case.")
        }
      },
      updateCaseAction: { caseId, startTime, procedure, patientName, surgeonId, targetBlockId in
        do {
          try await store.updateSchedulerCase(
            blockId: block.id,
            caseId: caseId,
            startTime: startTime,
            procedure: procedure,
            patientName: patientName,
            surgeonId: surgeonId,
            targetBlockId: targetBlockId
          )
        } catch {
          store.setWarningMessage(Self.friendlyWarning(error.localizedDescription) ?? "Couldn't update case.")
        }
      },
      clearAction: {
        do {
          try await store.clearSchedulerBlock(blockId: block.id)
          selectedBlock = nil
        } catch {
          store.setWarningMessage(Self.friendlyWarning(error.localizedDescription) ?? "Couldn't clear block. Reschedule linked cases first.")
        }
      },
      deleteBlockAction: {
        do {
          let containing = NativeDayResponse.dateFormatter.date(from: block.date) ?? selectedDate
          try await store.deleteSchedulerBlock(blockId: block.id, containing: containing)
          selectedBlock = nil
        } catch {
          store.setWarningMessage(Self.friendlyWarning(error.localizedDescription) ?? "Couldn't cancel block.")
          throw error
        }
      }
    )
  }

  private func blocks(on date: Date) -> [NativeSchedulerBlock] {
    let key = NativeDayResponse.dateFormatter.string(from: date)
    return store.schedulerBlocks.filter { $0.date == key }
  }

  private func groupedBlocks(_ blocks: [NativeSchedulerBlock]) -> [SchedulerBlockGroup] {
    Dictionary(grouping: blocks) { block in
      "\(block.date)|\(block.locationId)|\(block.session)|\(block.start)|\(block.end)"
    }
    .map { _, blocks in
      SchedulerBlockGroup(blocks: blocks)
    }
    .sorted { lhs, rhs in
      lhs.sortKey < rhs.sortKey
    }
  }

  private func step(_ direction: Int) {
    withAnimation(.easeInOut(duration: 0.2)) {
      switch scope {
      case .week:
        selectedDate = calendar.date(byAdding: .day, value: 7 * direction, to: selectedDate) ?? selectedDate
      case .day:
        selectedDate = calendar.date(byAdding: .day, value: direction, to: selectedDate) ?? selectedDate
      }
    }
  }

  /// Land on the Monday–Sunday work week that contains today (never day-scope “Today”).
  private func jumpToThisWeek() {
    let today = calendar.startOfDay(for: Date())
    withAnimation(.easeInOut(duration: 0.2)) {
      selectedDate = today
      scope = .week
    }
    Task { await store.loadScheduler(containing: today) }
  }

  /// First Monday that falls inside the next calendar month (so the week actually changes).
  private func jumpToNextMonth() {
    let parts = calendar.dateComponents([.year, .month], from: selectedDate)
    guard let thisMonthStart = calendar.date(from: parts),
          let nextMonthStart = calendar.date(byAdding: .month, value: 1, to: thisMonthStart) else {
      return
    }
    var target = calendar.dateInterval(of: .weekOfYear, for: nextMonthStart)?.start ?? nextMonthStart
    // Week containing the 1st often still starts in the previous month (e.g. Aug 1 → Jul 27).
    if calendar.component(.month, from: target) != calendar.component(.month, from: nextMonthStart) {
      target = calendar.date(byAdding: .day, value: 7, to: target) ?? nextMonthStart
    }
    withAnimation(.easeInOut(duration: 0.2)) {
      selectedDate = target
      scope = .week
    }
    Task { await store.loadScheduler(containing: target) }
  }

  fileprivate static func friendlyWarning(_ message: String?) -> String? {
    guard let message else { return nil }
    let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return nil }
    let lower = trimmed.lowercased()
    if lower == "not found" || lower == "404" || lower.hasSuffix(": not found") {
      return nil
    }
    if lower.contains("not found") {
      return "Couldn't load that item. Try refresh."
    }
    if lower.hasPrefix("scheduler sync failed") && lower.contains("not found") {
      return "Couldn't sync Block OR. Try refresh."
    }
    if lower.contains("network connection was lost") || lower.contains("NSURLErrorDomain") || lower.contains("-1005") {
      return "Network dropped. Check Wi‑Fi / VPN, then Retry."
    }
    if lower.contains("the internet connection appears to be offline") || lower.contains("-1009") {
      return "You're offline. Reconnect, then Retry."
    }
    return trimmed
  }

  /// Strip Desk fax / Kno2 / source= provenance from notes shown to schedulers.
  fileprivate static func humanScheduleNote(_ raw: String) -> String {
    var text = raw
    let patterns = [
      #"Desk fax\s*#\d+"#,
      #"Kno2\s+\S+"#,
      #"source=\S+"#,
      #"fax schedule"#,
      #"flags:\s*[^·]*"#,
    ]
    for pattern in patterns {
      text = text.replacingOccurrences(of: pattern, with: "", options: [.regularExpression, .caseInsensitive])
    }
    text = text
      .replacingOccurrences(of: #"\s*·\s*"#, with: " · ", options: .regularExpression)
      .replacingOccurrences(of: #"^[\s·]+|[\s·]+$"#, with: "", options: .regularExpression)
      .trimmingCharacters(in: .whitespacesAndNewlines)
    return text
  }
}

private struct SchedulerBlockGroup: Identifiable {
  let id: String
  let date: String
  let displayDate: String
  let locationId: Int
  let location: String
  let start: String
  let end: String
  let blocks: [NativeSchedulerBlock]

  var sortKey: String { "\(date)|\(String(format: "%05d", locationId))|\(start)|\(end)" }

  var sessionLabel: String {
    let raw = blocks.first?.session.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
    switch raw {
    case "am": return "AM"
    case "pm": return "PM"
    case "both": return "AM+PM"
    default: return raw.isEmpty ? "" : raw.uppercased()
    }
  }

  var roomCount: Int {
    let rooms = Set(blocks.map(\.displayRoom).filter { !$0.isEmpty })
    return max(rooms.count, blocks.count)
  }

  var roomSummary: String {
    let rooms = blocks.map(\.displayRoom).filter { !$0.isEmpty }
    var seen = Set<String>()
    var unique: [String] = []
    for room in rooms where seen.insert(room).inserted {
      unique.append(room)
    }
    if unique.isEmpty {
      return roomCount > 1 ? "\(roomCount) rooms" : ""
    }
    if unique.count == 1 {
      return "Rm \(unique[0])"
    }
    return "\(unique.count) rooms · " + unique.map { "Rm \($0)" }.joined(separator: ", ")
  }

  init(blocks: [NativeSchedulerBlock]) {
    let sortedBlocks = blocks.sorted { lhs, rhs in
      if lhs.displayRoom != rhs.displayRoom {
        return lhs.displayRoom < rhs.displayRoom
      }
      if lhs.isOpen != rhs.isOpen { return lhs.isOpen && !rhs.isOpen }
      return lhs.id < rhs.id
    }
    let first = sortedBlocks[0]
    self.blocks = sortedBlocks
    self.date = first.date
    self.displayDate = first.displayDate
    self.locationId = first.locationId
    self.location = first.displayLocation
    self.start = first.start
    self.end = first.end
    self.id = "\(first.date)|\(first.locationId)|\(first.session)|\(first.start)|\(first.end)"
  }
}

private struct SchedulerWeekDaySummary: Identifiable {
  let id: String
  let date: Date
  let blocks: [NativeSchedulerBlock]

  var openCount: Int { blocks.filter(\.isOpen).count }
  var assignedCount: Int { blocks.count - openCount }

  var hospitalBadges: [String] {
    var seen = Set<String>()
    var ordered: [String] = []
    for block in blocks {
      let label = block.displayLocation
      if seen.insert(label).inserted {
        ordered.append(label)
      }
    }
    return ordered
  }

  init(date: Date, blocks: [NativeSchedulerBlock]) {
    self.date = date
    self.blocks = blocks.sorted { lhs, rhs in
      if lhs.start != rhs.start { return lhs.start < rhs.start }
      return lhs.displayLocation < rhs.displayLocation
    }
    self.id = NativeDayResponse.dateFormatter.string(from: date)
  }
}

private struct SchedulerWeekView: View {
  let days: [SchedulerWeekDaySummary]
  let statusMessage: String?
  let selectDay: (Date) -> Void
  let addBlock: () -> Void

  private var weekIsEmpty: Bool {
    days.allSatisfy { $0.blocks.isEmpty }
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 10) {
        if let statusMessage {
          Label(statusMessage, systemImage: "exclamationmark.triangle")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
        }

        if weekIsEmpty {
          SchedulerEmptyState(
            text: "No Block OR this week.",
            addBlock: addBlock
          )
        } else {
          VStack(spacing: 7) {
            ForEach(days) { day in
              Button {
                selectDay(day.date)
              } label: {
                SchedulerWeekDayRow(day: day)
              }
              .buttonStyle(.plain)
            }
          }

          Button(action: addBlock) {
            Label("Add block", systemImage: "plus.circle.fill")
              .font(.subheadline.weight(.bold))
              .frame(maxWidth: .infinity)
              .padding(.vertical, 10)
          }
          .buttonStyle(.borderedProminent)
          .tint(ClinicalPalette.teal)
          .padding(.top, 4)
        }
      }
      .padding(16)
    }
  }
}

private struct SchedulerWeekDayRow: View {
  let day: SchedulerWeekDaySummary

  private var isToday: Bool {
    Calendar.current.isDateInToday(day.date)
  }

  var body: some View {
    HStack(alignment: .center, spacing: 10) {
      VStack(spacing: 1) {
        Text(day.date.formatted(.dateTime.weekday(.abbreviated)))
          .font(.caption2.weight(.bold))
          .foregroundStyle(.secondary)
        Text(day.date.formatted(.dateTime.day()))
          .font(.subheadline.weight(.bold))
          .foregroundStyle(isToday ? ClinicalPalette.teal : ClinicalPalette.ink)
      }
      .frame(width: 34)

      VStack(alignment: .leading, spacing: 4) {
        if day.blocks.isEmpty {
          Text("No blocks")
            .font(ClinicalTypography.caption)
            .foregroundStyle(.secondary)
        } else {
          Text(summaryLine)
            .font(ClinicalTypography.caption)
            .foregroundStyle(ClinicalPalette.ink)
            .lineLimit(1)
            .minimumScaleFactor(0.85)

          if !day.hospitalBadges.isEmpty {
            HStack(spacing: 4) {
              ForEach(day.hospitalBadges.prefix(4), id: \.self) { badge in
                Text(badge)
                  .font(ClinicalTypography.badge)
                  .foregroundStyle(ClinicalPalette.teal)
                  .padding(.horizontal, 6)
                  .padding(.vertical, 2)
                  .background(ClinicalPalette.teal.opacity(0.12), in: Capsule())
              }
              if day.hospitalBadges.count > 4 {
                Text("+\(day.hospitalBadges.count - 4)")
                  .font(ClinicalTypography.badge)
                  .foregroundStyle(.secondary)
              }
            }
          }
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)

      Image(systemName: "chevron.right")
        .font(.caption.weight(.semibold))
        .foregroundStyle(.secondary)
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 8)
    .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
    .contentShape(Rectangle())
    .liquidGlassCard(
      cornerRadius: 14,
      tint: isToday ? ClinicalPalette.tealSoft : ClinicalPalette.card
    )
  }

  private var summaryLine: String {
    var parts: [String] = []
    if day.openCount > 0 {
      parts.append("\(day.openCount) open")
    }
    if day.assignedCount > 0 {
      parts.append("\(day.assignedCount) assigned")
    }
    return parts.isEmpty ? "\(day.blocks.count) block\(day.blocks.count == 1 ? "" : "s")" : parts.joined(separator: " · ")
  }
}

private struct SchedulerDayDetailView: View {
  let blockGroups: [SchedulerBlockGroup]
  let statusMessage: String?
  let backToWeek: () -> Void
  let selectBlock: (NativeSchedulerBlock) -> Void
  let addBlock: () -> Void

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 12) {
        Button(action: backToWeek) {
          Label("Week", systemImage: "chevron.left")
            .font(ClinicalTypography.caption)
            .foregroundStyle(ClinicalPalette.teal)
        }
        .buttonStyle(.plain)

        if let statusMessage {
          Label(statusMessage, systemImage: "exclamationmark.triangle")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
        }

        if blockGroups.isEmpty {
          SchedulerEmptyState(
            text: "No Block OR on this day.",
            addBlock: addBlock
          )
        } else {
          ForEach(blockGroups) { group in
            VStack(alignment: .leading, spacing: 8) {
              HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(group.location)
                  .font(ClinicalTypography.headlineStrong)
                  .foregroundStyle(ClinicalPalette.teal)
                  .lineLimit(1)
                  .minimumScaleFactor(0.8)
                if !group.sessionLabel.isEmpty {
                  Text(group.sessionLabel)
                    .font(ClinicalTypography.badge)
                    .foregroundStyle(ClinicalPalette.teal)
                }
                Text("\(group.start)-\(group.end)")
                  .font(ClinicalTypography.caption)
                  .foregroundStyle(.secondary)
                  .lineLimit(1)
                  .minimumScaleFactor(0.85)
                Spacer(minLength: 0)
                if !group.roomSummary.isEmpty {
                  Text(group.roomSummary)
                    .font(ClinicalTypography.badge)
                    .foregroundStyle(ClinicalPalette.ink.opacity(0.7))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                }
              }

              ForEach(group.blocks) { block in
                Button {
                  selectBlock(block)
                } label: {
                  SchedulerBlockPill(block: block)
                }
                .buttonStyle(.plain)
              }
            }
            .padding(12)
            .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.tealSoft)
          }

          Button(action: addBlock) {
            Label("Add block", systemImage: "plus.circle.fill")
              .font(.subheadline.weight(.bold))
              .frame(maxWidth: .infinity)
              .padding(.vertical, 10)
          }
          .buttonStyle(.borderedProminent)
          .tint(ClinicalPalette.teal)
        }
      }
      .padding(16)
    }
  }
}

private struct SchedulerEmptyState: View {
  let text: String
  let addBlock: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text(text)
        .font(ClinicalTypography.rowTitle)
        .foregroundStyle(.secondary)
      Button(action: addBlock) {
        Label("Add block", systemImage: "plus.circle.fill")
          .font(.subheadline.weight(.bold))
          .frame(maxWidth: .infinity)
          .padding(.vertical, 10)
      }
      .buttonStyle(.borderedProminent)
      .tint(ClinicalPalette.teal)
    }
    .padding(14)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)
  }
}

private struct SchedulerBlockPill: View {
  let block: NativeSchedulerBlock

  var body: some View {
    HStack(alignment: .center, spacing: 10) {
      VStack(alignment: .leading, spacing: 4) {
        HStack(spacing: 6) {
          Text(block.session.uppercased())
            .font(ClinicalTypography.badge)
            .foregroundStyle(ClinicalPalette.ink)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(ClinicalPalette.tealSoft, in: Capsule())
          if !block.displayRoom.isEmpty {
            Text(block.displayRoom.contains(",") ? block.displayRoom : "Rm \(block.displayRoom)")
              .font(ClinicalTypography.badge)
              .foregroundStyle(ClinicalPalette.teal)
              .padding(.horizontal, 6)
              .padding(.vertical, 2)
              .background(ClinicalPalette.teal.opacity(0.12), in: Capsule())
          }
          if !block.cases.isEmpty {
            Text("\(block.cases.count) case\(block.cases.count == 1 ? "" : "s")")
              .font(ClinicalTypography.caption)
              .foregroundStyle(.secondary)
          } else if block.caseCount > 0 {
            Text("\(block.caseCount) case\(block.caseCount == 1 ? "" : "s")")
              .font(ClinicalTypography.caption)
              .foregroundStyle(.secondary)
          }
        }

        if block.assignments.isEmpty {
          Text("Open — tap to assign surgeon")
            .font(.caption.weight(.bold))
            .foregroundStyle(ClinicalPalette.teal)
        } else {
          ForEach(block.assignments.sorted { lhs, rhs in lhs.start < rhs.start }) { assignment in
            Text(assignment.label)
              .font(.caption.weight(.bold))
              .foregroundStyle(ClinicalPalette.ink)
          }
        }
      }
      Spacer()
      Image(systemName: block.isOpen ? "chevron.right.circle.fill" : "checkmark.circle.fill")
        .foregroundStyle(block.isOpen ? ClinicalPalette.teal : .green)
    }
    .padding(10)
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(block.isOpen ? Color.white.opacity(0.45) : Color.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
  }
}

private struct SchedulerAssignSheet: View {
  let block: NativeSchedulerBlock
  let detail: NativeSchedulerBlockDetailResponse?
  let dayBlocks: [NativeSchedulerBlock]
  let loadBlocksOnDate: (Date) async throws -> [NativeSchedulerBlock]
  let createBlockOnDate: (Date) async throws -> NativeSchedulerBlock?
  let isLoading: Bool
  let assignAction: (NativeSchedulerCandidate, String, Int, String) async -> Void
  let addCaseAction: (Int, String, String, String) async -> Void
  let updateCaseAction: (Int, String, String, String, Int?, Int?) async -> Void
  let clearAction: () async -> Void
  let deleteBlockAction: () async throws -> Void
  @Environment(\.dismiss) private var dismiss
  @State private var mode: SheetMode = .idle
  @State private var focusedAssignmentId: Int?
  @State private var editingCaseId: Int?
  @State private var selectedCandidate: NativeSchedulerCandidate?
  @State private var startTime: Date = Date()
  @State private var caseCount = 1
  @State private var note = ""
  @State private var procedureText = ""
  @State private var patientText = ""
  @State private var caseSurgeonId: Int?
  @State private var caseTargetBlockId: Int?
  @State private var destinationDate: Date = Date()
  @State private var destinationBlocks: [NativeSchedulerBlock] = []
  @State private var isLoadingDestination = false
  @State private var showUnavailable = false
  @State private var didSeedDefaults = false
  @State private var isSaving = false
  @State private var showCancelConfirm = false
  @State private var showClearConfirm = false
  @State private var actionError: String?

  /// Block → surgeons (1:N). Surgeon → cases (1:N). Never mix both levels on one screen.
  private enum SheetMode {
    case idle
    case addingSurgeon
    case addingCase
    case editingCase
  }

  private var liveBlock: NativeSchedulerBlock {
    detail?.block ?? block
  }

  private var assignedRows: [NativeSchedulerBlockAssignment] {
    liveBlock.assignments.sorted { lhs, rhs in
      if lhs.start != rhs.start { return lhs.start < rhs.start }
      return lhs.id < rhs.id
    }
  }

  private var focusedAssignment: NativeSchedulerBlockAssignment? {
    guard let focusedAssignmentId else { return nil }
    return assignedRows.first { $0.id == focusedAssignmentId }
  }

  /// True when drilled into one surgeon's case list (child of the block).
  private var isSurgeonDrillIn: Bool {
    focusedAssignment != nil && mode != .addingSurgeon
  }

  private var focusedCases: [NativeSchedulerCase] {
    guard let focused = focusedAssignment else { return [] }
    return liveBlock.cases
      .filter { $0.surgeonId == focused.surgeonId }
      .sorted { lhs, rhs in
        if lhs.start != rhs.start { return lhs.start < rhs.start }
        return lhs.id < rhs.id
      }
  }

  private var candidates: [NativeSchedulerCandidate] {
    detail?.candidates ?? []
  }

  private var availableCandidates: [NativeSchedulerCandidate] {
    candidates.filter { $0.isClear }
  }

  private var unavailableCandidates: [NativeSchedulerCandidate] {
    candidates.filter { !$0.isClear }
  }

  private var currentStartHHMM: String { Self.hhmm(startTime) }

  private var canSaveSurgeon: Bool {
    guard mode == .addingSurgeon, let candidate = selectedCandidate, !isLoading, !isSaving else { return false }
    if !candidate.isClear && note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return false
    }
    return true
  }

  private var linkedCaseCount: Int {
    liveBlock.cases.count
  }

  private var hasLinkedCases: Bool {
    linkedCaseCount > 0
  }

  private var canClearSurgeons: Bool {
    !assignedRows.isEmpty && !hasLinkedCases && !isLoading && !isSaving
  }

  private var canCancelBlock: Bool {
    assignedRows.isEmpty && !hasLinkedCases && !isLoading && !isSaving
  }

  private var canSaveCase: Bool {
    guard !isLoading, !isSaving else { return false }
    if mode == .addingCase { return true }
    if mode == .editingCase {
      return caseSurgeonId != nil && caseTargetBlockId != nil
    }
    return false
  }

  private var rescheduleBlocks: [NativeSchedulerBlock] {
    let rows = destinationBlocks.isEmpty && Self.dateKey(destinationDate) == liveBlock.date
      ? (dayBlocks.isEmpty ? [liveBlock] : dayBlocks)
      : destinationBlocks
    return rows.sorted { lhs, rhs in
      if lhs.start != rhs.start { return lhs.start < rhs.start }
      return lhs.displayLocation < rhs.displayLocation
    }
  }

  private var caseSurgeonChoices: [(id: Int, label: String)] {
    var seen = Set<Int>()
    var rows: [(Int, String)] = []
    let preferBlockId = caseTargetBlockId ?? liveBlock.id
    let preferBlock = rescheduleBlocks.first(where: { $0.id == preferBlockId }) ?? liveBlock
    for assignment in preferBlock.assignments {
      if seen.insert(assignment.surgeonId).inserted {
        let name = assignment.surgeon.isEmpty ? assignment.surgeonInitials : assignment.surgeon
        rows.append((assignment.surgeonId, "\(assignment.surgeonInitials) — \(name)"))
      }
    }
    for assignment in assignedRows {
      if seen.insert(assignment.surgeonId).inserted {
        let name = assignment.surgeon.isEmpty ? assignment.surgeonInitials : assignment.surgeon
        rows.append((assignment.surgeonId, "\(assignment.surgeonInitials) — \(name)"))
      }
    }
    for block in rescheduleBlocks {
      for assignment in block.assignments where seen.insert(assignment.surgeonId).inserted {
        let name = assignment.surgeon.isEmpty ? assignment.surgeonInitials : assignment.surgeon
        rows.append((assignment.surgeonId, "\(assignment.surgeonInitials) — \(name)"))
      }
    }
    for candidate in candidates where seen.insert(candidate.surgeonId).inserted {
      rows.append((candidate.surgeonId, "\(candidate.initials) — \(candidate.name)"))
    }
    return rows
  }

  private var navigationTitle: String {
    if let focused = focusedAssignment {
      let name = focused.surgeon.isEmpty ? focused.surgeonInitials : focused.surgeon
      return name.isEmpty ? "Cases" : name
    }
    return assignedRows.isEmpty ? "Assign Block" : "Block surgeons"
  }

  var body: some View {
    CalNavigation {
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          blockHeader

          if let actionError {
            Text(NativeSchedulerShell.friendlyWarning(actionError) ?? actionError)
              .font(.caption.weight(.semibold))
              .foregroundStyle(ClinicalPalette.warningText)
              .fixedSize(horizontal: false, vertical: true)
          }

          if isSurgeonDrillIn, let focused = focusedAssignment {
            surgeonCasesLevel(focused)
          } else {
            surgeonsLevel
          }

          if mode == .addingCase || mode == .editingCase {
            caseEditorCard
          }

          if mode == .addingSurgeon || assignedRows.isEmpty {
            surgeonPickerCard
          }

          if !isSurgeonDrillIn {
            blockDangerZone
          }
        }
        .padding(16)
      }
      .background(ScheduleWaterBackground())
      .navigationTitle(navigationTitle)
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          if isSurgeonDrillIn {
            Button {
              backToSurgeons()
            } label: {
              Label("Surgeons", systemImage: "chevron.left")
            }
            .disabled(isSaving)
          } else {
            Button("Done") { dismiss() }
          }
        }
      }
      .alert(
        "Clear all surgeons from this block?",
        isPresented: $showClearConfirm
      ) {
        Button("Keep surgeons", role: .cancel) {}
        Button("Clear surgeons", role: .destructive) {
          Task {
            isSaving = true
            defer { isSaving = false }
            await clearAction()
          }
        }
      } message: {
        Text("Only allowed when this block has no linked cases. Removes every surgeon assignment on \(liveBlock.displayLocation) \(liveBlock.start)-\(liveBlock.end). This cannot be undone in the app.")
      }
      .alert(
        "Cancel this Block OR window?",
        isPresented: $showCancelConfirm
      ) {
        Button("Keep block", role: .cancel) {}
        Button("Cancel block", role: .destructive) {
          Task {
            isSaving = true
            defer { isSaving = false }
            do {
              try await deleteBlockAction()
              dismiss()
            } catch {
              actionError = error.localizedDescription
            }
          }
        }
      } message: {
        Text("Deletes the empty hospital window \(liveBlock.displayLocation) \(liveBlock.start)-\(liveBlock.end). Only allowed when there are no surgeons and no linked cases.")
      }
      .onAppear {
        seedDefaultsIfNeeded()
      }
      .onChange(of: assignedRows.map(\.id)) { ids in
        if let focusedAssignmentId, !ids.contains(focusedAssignmentId) {
          resetToIdle()
        }
      }
      .onChange(of: detail?.candidates.count ?? 0) { _ in
        seedDefaultsIfNeeded()
      }
    }
  }

  private var blockHeader: some View {
    HStack(alignment: .firstTextBaseline) {
      VStack(alignment: .leading, spacing: 2) {
        Text("\(liveBlock.displayLocation)  \(liveBlock.start)-\(liveBlock.end)")
          .font(ClinicalTypography.headlineStrong)
          .foregroundStyle(ClinicalPalette.ink)
        HStack(spacing: 6) {
          Text(liveBlock.displayDate)
            .font(ClinicalTypography.caption)
            .foregroundStyle(.secondary)
          if !liveBlock.displayRoom.isEmpty {
            Text("·")
              .foregroundStyle(.secondary)
            Text("Rm \(liveBlock.displayRoom)")
              .font(ClinicalTypography.caption)
              .foregroundStyle(ClinicalPalette.teal)
          }
        }
        if isSurgeonDrillIn {
          Text("1 surgeon · \(focusedCases.count) case\(focusedCases.count == 1 ? "" : "s")")
            .font(ClinicalTypography.caption)
            .foregroundStyle(.secondary)
        } else if !assignedRows.isEmpty {
          Text("\(assignedRows.count) surgeon\(assignedRows.count == 1 ? "" : "s") on this block")
            .font(ClinicalTypography.caption)
            .foregroundStyle(.secondary)
        }
      }
      Spacer()
      if isLoading || isSaving {
        ProgressView()
      }
    }
  }

  @ViewBuilder
  private var surgeonsLevel: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("SURGEONS")
        .font(ClinicalTypography.sectionLabel)
        .foregroundStyle(.secondary)
      Text("Each surgeon has their own cases. Tap one to open that list.")
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)

      if assignedRows.isEmpty {
        Text("No surgeons yet — pick one below")
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(.secondary)
      } else {
        ForEach(assignedRows) { assignment in
          AssignedSurgeonPill(
            assignment: assignment,
            caseCountOverride: {
              let real = liveBlock.cases.filter { $0.surgeonId == assignment.surgeonId }.count
              return real > 0 ? real : nil
            }(),
            isSelected: false,
            isBusy: isLoading || isSaving,
            onSelect: { focusSurgeon(assignment) }
          )
        }
      }

      if mode == .idle, !assignedRows.isEmpty {
        Button {
          beginAddingSurgeon()
        } label: {
          Label("Add another surgeon", systemImage: "plus.circle.fill")
            .font(.subheadline.weight(.bold))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
        }
        .buttonStyle(.bordered)
        .tint(ClinicalPalette.teal)
        .disabled(isLoading || isSaving)
      }
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)
  }

  @ViewBuilder
  private func surgeonCasesLevel(_ focused: NativeSchedulerBlockAssignment) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("CASES")
        .font(ClinicalTypography.sectionLabel)
        .foregroundStyle(.secondary)

      HStack(spacing: 10) {
        Text(focused.surgeonInitials.isEmpty ? "—" : focused.surgeonInitials)
          .font(ClinicalTypography.sectionLabel)
          .foregroundStyle(.white)
          .padding(.horizontal, 10)
          .padding(.vertical, 6)
          .background(ClinicalPalette.teal, in: Capsule())
        VStack(alignment: .leading, spacing: 2) {
          Text(focused.surgeon.isEmpty ? focused.surgeonInitials : focused.surgeon)
            .font(ClinicalTypography.rowTitleStrong)
            .foregroundStyle(ClinicalPalette.ink)
          Text("On this block from \(focused.start)")
            .font(ClinicalTypography.caption)
            .foregroundStyle(.secondary)
        }
        Spacer(minLength: 0)
      }

      SurgeonCasesPanel(
        surgeonName: focused.surgeon.isEmpty ? focused.surgeonInitials : focused.surgeon,
        cases: focusedCases,
        selectedCaseId: editingCaseId,
        onSelectCase: { beginEditingCase($0) }
      )

      if mode == .idle {
        Button {
          beginAddingCase(for: focused)
        } label: {
          Label(addCaseButtonTitle(for: focused), systemImage: "plus.circle.fill")
            .font(.subheadline.weight(.bold))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
        }
        .buttonStyle(.borderedProminent)
        .tint(ClinicalPalette.teal)
        .disabled(isLoading || isSaving)
      }
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)
  }

  @ViewBuilder
  private var blockDangerZone: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("BLOCK ACTIONS")
        .font(ClinicalTypography.sectionLabel)
        .foregroundStyle(.secondary)

      if hasLinkedCases {
        Text("This block has \(linkedCaseCount) linked case\(linkedCaseCount == 1 ? "" : "s"). Reschedule those cases off this block before clearing surgeons or canceling the window.")
          .font(.caption.weight(.semibold))
          .foregroundStyle(ClinicalPalette.warningText)
          .fixedSize(horizontal: false, vertical: true)
      }

      if !assignedRows.isEmpty {
        Button(role: .destructive) {
          showClearConfirm = true
        } label: {
          Text(hasLinkedCases ? "Clear surgeons (blocked — cases first)" : "Clear all surgeons…")
            .font(.caption.weight(.bold))
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(!canClearSurgeons)
      }

      Button(role: .destructive) {
        showCancelConfirm = true
      } label: {
        Text(cancelBlockButtonTitle)
          .font(.caption.weight(.bold))
          .frame(maxWidth: .infinity)
      }
      .buttonStyle(.bordered)
      .disabled(!canCancelBlock)
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)
  }

  private var cancelBlockButtonTitle: String {
    if hasLinkedCases {
      return "Cancel block (reschedule cases first)"
    }
    if !assignedRows.isEmpty {
      return "Cancel block (clear surgeons first)"
    }
    return "Cancel this block…"
  }

  @ViewBuilder
  private var caseEditorCard: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text(mode == .editingCase ? "RESCHEDULE CASE" : "ADD CASE")
        .font(ClinicalTypography.sectionLabel)
        .foregroundStyle(.secondary)

      if mode == .editingCase {
        Text("Insurance, illness, or other cancel → pick any future day and block. Create a block on that day if none exists.")
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)
          .fixedSize(horizontal: false, vertical: true)

        DatePicker(
          "New date",
          selection: $destinationDate,
          displayedComponents: .date
        )
        .font(.subheadline.weight(.semibold))
        .onChange(of: destinationDate) { _ in
          Task { await reloadDestinationBlocks(selectFirst: true) }
        }

        if isLoadingDestination {
          HStack(spacing: 8) {
            ProgressView()
            Text("Loading blocks…")
              .font(.caption.weight(.semibold))
              .foregroundStyle(.secondary)
          }
        } else if rescheduleBlocks.isEmpty {
          Text("No Block OR on \(Self.dateKey(destinationDate)). Create one to move this patient.")
            .font(.caption.weight(.semibold))
            .foregroundStyle(ClinicalPalette.warningText)
            .fixedSize(horizontal: false, vertical: true)
          Button {
            Task { await createDestinationBlock() }
          } label: {
            Label(
              "Create \(liveBlock.displayLocation) \(liveBlock.start)-\(liveBlock.end) on this day",
              systemImage: "plus.circle.fill"
            )
            .font(.subheadline.weight(.bold))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
          }
          .buttonStyle(.borderedProminent)
          .tint(ClinicalPalette.teal)
          .disabled(isSaving)
        } else {
          Picker("Block", selection: $caseTargetBlockId) {
            ForEach(rescheduleBlocks) { destination in
              Text(blockChoiceLabel(destination)).tag(Optional(destination.id))
            }
          }
          .pickerStyle(.menu)
        }

        if !caseSurgeonChoices.isEmpty {
          Picker("Surgeon", selection: $caseSurgeonId) {
            ForEach(caseSurgeonChoices, id: \.id) { row in
              Text(row.label).tag(Optional(row.id))
            }
          }
          .pickerStyle(.menu)
        }

        if let targetId = caseTargetBlockId, targetId != liveBlock.id {
          Text("Saving reschedules this patient off \(liveBlock.displayLocation) \(liveBlock.displayDate).")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(ClinicalPalette.warningText)
            .fixedSize(horizontal: false, vertical: true)
        }
      } else if let focused = focusedAssignment {
        Text(focused.surgeon.isEmpty ? focused.surgeonInitials : focused.surgeon)
          .font(.subheadline.weight(.bold))
          .foregroundStyle(ClinicalPalette.ink)
      }

      DatePicker("Start time", selection: $startTime, displayedComponents: .hourAndMinute)
        .labelsHidden()
        .font(.subheadline.weight(.semibold))
      TextField("Procedure (optional)", text: $procedureText)
        .textFieldStyle(.roundedBorder)
      TextField("Patient (optional)", text: $patientText)
        .textFieldStyle(.roundedBorder)
      Button {
        Task { await saveCase() }
      } label: {
        Text(mode == .editingCase ? "Save reschedule · \(currentStartHHMM)" : "Add case · \(currentStartHHMM)")
          .font(.headline.weight(.bold))
          .frame(maxWidth: .infinity)
          .padding(.vertical, 12)
      }
      .buttonStyle(.borderedProminent)
      .tint(ClinicalPalette.teal)
      .disabled(!canSaveCase)
      Button("Cancel") {
        mode = .idle
        editingCaseId = nil
        procedureText = ""
        patientText = ""
        caseSurgeonId = nil
        caseTargetBlockId = nil
      }
      .font(.caption.weight(.bold))
      .frame(maxWidth: .infinity)
      .disabled(isSaving)
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.tealSoft)
  }

  private func blockChoiceLabel(_ destination: NativeSchedulerBlock) -> String {
    let room = destination.displayRoom.isEmpty ? "" : " · Rm \(destination.displayRoom)"
    let here = destination.id == liveBlock.id ? " (current)" : ""
    return "\(destination.displayLocation) \(destination.start)-\(destination.end)\(room)\(here)"
  }

  @ViewBuilder
  private var surgeonPickerCard: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("ADD SURGEON")
        .font(ClinicalTypography.sectionLabel)
        .foregroundStyle(.secondary)
      HStack(spacing: 12) {
        DatePicker("Start", selection: $startTime, displayedComponents: .hourAndMinute)
          .labelsHidden()
          .font(.subheadline.weight(.semibold))
        Stepper("\(caseCount) case\(caseCount == 1 ? "" : "s")", value: $caseCount, in: 1...20)
          .font(.subheadline.weight(.semibold))
      }
      TextField(
        selectedCandidate?.isClear == false ? "Override note (required)" : "Note (optional)",
        text: $note
      )
      .textFieldStyle(.roundedBorder)
      if let candidate = selectedCandidate, !candidate.isClear {
        Text(candidate.warnings.first ?? candidate.availability)
          .font(.caption2.weight(.semibold))
          .foregroundStyle(ClinicalPalette.warningText)
      }

      Text("PICK SURGEON")
        .font(ClinicalTypography.sectionLabel)
        .foregroundStyle(.secondary)
        .padding(.top, 4)

      if candidates.isEmpty {
        HStack(spacing: 8) {
          ProgressView()
          Text("Loading availability…")
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.secondary)
        }
      } else if availableCandidates.isEmpty {
        Text("No clear surgeons for this block.")
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(.secondary)
      } else {
        ForEach(availableCandidates) { candidate in
          CandidatePickRow(
            candidate: candidate,
            isSelected: selectedCandidate?.surgeonId == candidate.surgeonId
          ) {
            selectedCandidate = candidate
          }
        }
      }

      if !unavailableCandidates.isEmpty {
        DisclosureGroup(isExpanded: $showUnavailable) {
          ForEach(unavailableCandidates) { candidate in
            CandidatePickRow(
              candidate: candidate,
              isSelected: selectedCandidate?.surgeonId == candidate.surgeonId
            ) {
              selectedCandidate = candidate
            }
          }
        } label: {
          Text("Not available (\(unavailableCandidates.count))")
            .font(.caption.weight(.black))
            .foregroundStyle(.secondary)
        }
        .padding(.top, 4)
      }

      Button {
        Task { await saveSurgeon() }
      } label: {
        Text(selectedCandidate.map { "Add \($0.initials) · \(currentStartHHMM)" } ?? "Select a surgeon")
          .font(.headline.weight(.bold))
          .frame(maxWidth: .infinity)
          .padding(.vertical, 12)
      }
      .buttonStyle(.borderedProminent)
      .tint(ClinicalPalette.teal)
      .disabled(!canSaveSurgeon)

      if mode == .addingSurgeon, !assignedRows.isEmpty {
        Button("Cancel") {
          resetToIdle()
        }
        .font(.caption.weight(.bold))
        .frame(maxWidth: .infinity)
        .disabled(isSaving)
      }
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)
  }

  private func seedDefaultsIfNeeded() {
    guard !didSeedDefaults else { return }
    didSeedDefaults = true
    if assignedRows.isEmpty {
      mode = .addingSurgeon
      caseCount = 1
      note = ""
      startTime = Self.dateForTime(liveBlock.start)
    } else {
      resetToIdle()
    }
  }

  private func focusSurgeon(_ assignment: NativeSchedulerBlockAssignment) {
    focusedAssignmentId = assignment.id
    mode = .idle
    editingCaseId = nil
    selectedCandidate = nil
    procedureText = ""
    patientText = ""
    actionError = nil
  }

  private func backToSurgeons() {
    focusedAssignmentId = nil
    editingCaseId = nil
    mode = .idle
    procedureText = ""
    patientText = ""
    actionError = nil
  }

  private func beginAddingSurgeon() {
    mode = .addingSurgeon
    focusedAssignmentId = nil
    editingCaseId = nil
    selectedCandidate = nil
    caseCount = 1
    note = ""
    startTime = Self.suggestedStart(
      blockStart: liveBlock.start,
      blockEnd: liveBlock.end,
      takenStarts: assignedRows.map(\.start)
    )
  }

  private func beginAddingCase(for assignment: NativeSchedulerBlockAssignment) {
    mode = .addingCase
    editingCaseId = nil
    focusedAssignmentId = assignment.id
    procedureText = ""
    patientText = ""
    let anchors = focusedCases.compactMap { row -> String? in
      row.end.isEmpty ? (row.start.isEmpty ? nil : row.start) : row.end
    }
    startTime = Self.suggestedStart(
      blockStart: liveBlock.start,
      blockEnd: liveBlock.end,
      takenStarts: anchors.isEmpty ? [assignment.start] : anchors
    )
  }

  private func beginEditingCase(_ surgicalCase: NativeSchedulerCase) {
    mode = .editingCase
    editingCaseId = surgicalCase.id
    startTime = Self.dateForTime(surgicalCase.start.isEmpty ? liveBlock.start : surgicalCase.start)
    procedureText = surgicalCase.procedure
    patientText = surgicalCase.patientName
    caseSurgeonId = surgicalCase.surgeonId ?? focusedAssignment?.surgeonId
    caseTargetBlockId = liveBlock.id
    destinationDate = Self.dateForDateKey(liveBlock.date) ?? Date()
    destinationBlocks = dayBlocks.isEmpty ? [liveBlock] : dayBlocks
    Task { await reloadDestinationBlocks(selectFirst: false) }
  }

  private func reloadDestinationBlocks(selectFirst: Bool) async {
    isLoadingDestination = true
    defer { isLoadingDestination = false }
    do {
      let rows = try await loadBlocksOnDate(destinationDate)
      destinationBlocks = rows
      if selectFirst {
        caseTargetBlockId = rows.first?.id
        if let first = rows.first?.assignments.first?.surgeonId {
          caseSurgeonId = first
        }
      } else if let current = caseTargetBlockId, !rows.contains(where: { $0.id == current }) {
        caseTargetBlockId = rows.first?.id ?? liveBlock.id
      }
    } catch {
      actionError = error.localizedDescription
      destinationBlocks = []
      if selectFirst {
        caseTargetBlockId = nil
      }
    }
  }

  private func createDestinationBlock() async {
    isSaving = true
    defer { isSaving = false }
    do {
      let created = try await createBlockOnDate(destinationDate)
      await reloadDestinationBlocks(selectFirst: false)
      if let created {
        destinationBlocks = destinationBlocks.contains(where: { $0.id == created.id })
          ? destinationBlocks
          : destinationBlocks + [created]
        caseTargetBlockId = created.id
      } else {
        caseTargetBlockId = destinationBlocks.first?.id
      }
    } catch {
      actionError = error.localizedDescription
    }
  }

  private func addCaseButtonTitle(for assignment: NativeSchedulerBlockAssignment) -> String {
    let anchors = focusedCases.compactMap { row -> String? in
      row.end.isEmpty ? (row.start.isEmpty ? nil : row.start) : row.end
    }
    let after = anchors.max() ?? assignment.start
    if after.isEmpty {
      return "Add another case"
    }
    return "Add another case after \(after)"
  }

  private func resetToIdle() {
    mode = assignedRows.isEmpty ? .addingSurgeon : .idle
    focusedAssignmentId = nil
    editingCaseId = nil
    selectedCandidate = nil
    caseCount = 1
    note = ""
    procedureText = ""
    patientText = ""
    if assignedRows.isEmpty {
      startTime = Self.dateForTime(liveBlock.start)
    }
  }

  private func saveSurgeon() async {
    guard let candidate = selectedCandidate, canSaveSurgeon else { return }
    isSaving = true
    defer { isSaving = false }
    await assignAction(candidate, currentStartHHMM, caseCount, note)
    resetToIdle()
  }

  private func saveCase() async {
    guard canSaveCase, let focused = focusedAssignment else { return }
    isSaving = true
    defer { isSaving = false }
    switch mode {
    case .addingCase:
      await addCaseAction(focused.surgeonId, currentStartHHMM, procedureText, patientText)
      mode = .idle
      editingCaseId = nil
      procedureText = ""
      patientText = ""
      caseSurgeonId = nil
      caseTargetBlockId = nil
    case .editingCase:
      guard let editingCaseId else { return }
      let nextSurgeonId = caseSurgeonId
      let nextBlockId = caseTargetBlockId
      await updateCaseAction(
        editingCaseId,
        currentStartHHMM,
        procedureText,
        patientText,
        nextSurgeonId,
        nextBlockId
      )
      mode = .idle
      self.editingCaseId = nil
      procedureText = ""
      patientText = ""
      caseSurgeonId = nil
      caseTargetBlockId = nil
      if let nextSurgeonId, nextSurgeonId != focused.surgeonId {
        backToSurgeons()
      } else if let nextBlockId, nextBlockId != liveBlock.id {
        backToSurgeons()
      }
    default:
      break
    }
  }

  private static func hhmm(_ date: Date) -> String {
    let formatter = DateFormatter()
    formatter.dateFormat = "HH:mm"
    return formatter.string(from: date)
  }

  private static func dateForTime(_ value: String) -> Date {
    let formatter = DateFormatter()
    formatter.dateFormat = "HH:mm"
    return formatter.date(from: value) ?? Date()
  }

  private static func suggestedStart(blockStart: String, blockEnd: String, takenStarts: [String]) -> Date {
    let start = dateForTime(blockStart)
    let end = dateForTime(blockEnd)
    guard !takenStarts.isEmpty, let latestTaken = takenStarts.map(dateForTime).max() else {
      return start
    }

    var calendar = Calendar.current
    calendar.timeZone = .current
    let next = calendar.date(byAdding: .minute, value: 60, to: latestTaken) ?? start

    if next < start { return start }
    if next >= end {
      let fallback = calendar.date(byAdding: .hour, value: -1, to: end) ?? start
      return max(start, fallback)
    }
    return next
  }

  private static func dateKey(_ date: Date) -> String {
    NativeDayResponse.dateFormatter.string(from: ClinicalCalendar.mondayFirst.startOfDay(for: date))
  }

  private static func dateForDateKey(_ value: String) -> Date? {
    NativeDayResponse.dateFormatter.date(from: value)
  }
}

private struct AssignedSurgeonPill: View {
  let assignment: NativeSchedulerBlockAssignment
  var caseCountOverride: Int? = nil
  let isSelected: Bool
  let isBusy: Bool
  let onSelect: () -> Void

  private var caseCount: Int {
    caseCountOverride ?? assignment.caseCount
  }

  var body: some View {
    Button(action: onSelect) {
      HStack(spacing: 10) {
        Text(assignment.surgeonInitials.isEmpty ? "—" : assignment.surgeonInitials)
          .font(ClinicalTypography.sectionLabel)
          .foregroundStyle(.white)
          .padding(.horizontal, 10)
          .padding(.vertical, 6)
          .background(isSelected ? ClinicalPalette.teal : ClinicalPalette.teal.opacity(0.75), in: Capsule())
        VStack(alignment: .leading, spacing: 2) {
          Text(assignment.surgeon.isEmpty ? assignment.label : assignment.surgeon)
            .font(ClinicalTypography.rowTitleStrong)
            .foregroundStyle(ClinicalPalette.ink)
            .lineLimit(1)
            .minimumScaleFactor(0.85)
          Text("\(assignment.start) · \(caseCount) case\(caseCount == 1 ? "" : "s")")
            .font(ClinicalTypography.caption)
            .foregroundStyle(.secondary)
        }
        Spacer(minLength: 0)
        Image(systemName: "chevron.right")
          .font(.caption.weight(.semibold))
          .foregroundStyle(.tertiary)
      }
      .padding(.horizontal, 10)
      .padding(.vertical, 8)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(
        isSelected ? ClinicalPalette.teal.opacity(0.12) : Color.white.opacity(0.7),
        in: RoundedRectangle(cornerRadius: 12, style: .continuous)
      )
      .overlay(
        RoundedRectangle(cornerRadius: 12, style: .continuous)
          .stroke(isSelected ? ClinicalPalette.teal.opacity(0.5) : Color.clear, lineWidth: 1.5)
      )
    }
    .buttonStyle(.plain)
    .disabled(isBusy)
  }
}

private struct SurgeonCasesPanel: View {
  let surgeonName: String
  let cases: [NativeSchedulerCase]
  let selectedCaseId: Int?
  let onSelectCase: (NativeSchedulerCase) -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      Text("\(surgeonName)'s cases")
        .font(ClinicalTypography.caption)
        .foregroundStyle(.secondary)
      if cases.isEmpty {
        Text("No cases yet — add the first case for this surgeon.")
          .font(.caption2)
          .foregroundStyle(.secondary)
          .fixedSize(horizontal: false, vertical: true)
      } else {
        ForEach(cases) { surgicalCase in
          Button {
            onSelectCase(surgicalCase)
          } label: {
            VStack(alignment: .leading, spacing: 2) {
              Text(surgicalCase.timeLabel)
                .font(ClinicalTypography.monoCaption)
                .foregroundStyle(ClinicalPalette.teal)
              Text(surgicalCase.detailLine.isEmpty ? "Case" : surgicalCase.detailLine)
                .font(ClinicalTypography.caption)
                .foregroundStyle(ClinicalPalette.ink)
                .lineLimit(2)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
              selectedCaseId == surgicalCase.id
                ? ClinicalPalette.teal.opacity(0.14)
                : Color.white.opacity(0.75),
              in: RoundedRectangle(cornerRadius: 10, style: .continuous)
            )
          }
          .buttonStyle(.plain)
        }
        Text("Tap a case to reschedule (any day), change surgeon, or edit time")
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)
      }
    }
    .padding(.top, 4)
  }
}

private struct CandidatePickRow: View {
  let candidate: NativeSchedulerCandidate
  let isSelected: Bool
  let action: () -> Void

  var body: some View {
    Button(action: action) {
      HStack(alignment: .center, spacing: 10) {
        Text(candidate.initials)
          .font(ClinicalTypography.sectionLabel)
          .foregroundStyle(candidate.isClear ? ClinicalPalette.teal : .secondary)
          .padding(.horizontal, 10)
          .padding(.vertical, 6)
          .background(Color(.secondarySystemBackground), in: Capsule())
        VStack(alignment: .leading, spacing: 2) {
          Text(candidate.name)
            .font(ClinicalTypography.rowTitleStrong)
            .foregroundStyle(ClinicalPalette.ink)
            .lineLimit(1)
            .minimumScaleFactor(0.85)
          Text(candidate.availability)
            .font(.caption)
            .foregroundStyle(candidate.isClear ? Color.secondary : Color.orange)
            .lineLimit(2)
        }
        Spacer(minLength: 0)
        if isSelected {
          Image(systemName: "checkmark.circle.fill")
            .foregroundStyle(ClinicalPalette.teal)
        }
      }
      .padding(.horizontal, 10)
      .padding(.vertical, 8)
      .background(
        isSelected ? ClinicalPalette.teal.opacity(0.12) : Color.white.opacity(0.45),
        in: RoundedRectangle(cornerRadius: 12, style: .continuous)
      )
      .overlay(
        RoundedRectangle(cornerRadius: 12, style: .continuous)
          .stroke(isSelected ? ClinicalPalette.teal.opacity(0.45) : Color.clear, lineWidth: 1.5)
      )
    }
    .buttonStyle(.plain)
  }
}

private struct SchedulerCreateBlockSheet: View {
  let initialDate: Date
  let loadMeta: () async throws -> NativeSchedulerMetaResponse
  let createAction: (Date, Int, String, String?, String?, String) async throws -> Void
  @Environment(\.dismiss) private var dismiss
  @State private var date = Date()
  @State private var hospitals: [NativeSchedulerHospital] = []
  @State private var locationId: Int = 0
  @State private var session = "am"
  @State private var startTime = Date()
  @State private var endTime = Date()
  @State private var notes = ""
  @State private var isSaving = false
  @State private var isLoadingHospitals = true
  @State private var hospitalsError: String?
  @State private var errorMessage: String?
  @State private var didLoad = false

  private var canCreate: Bool {
    locationId > 0 && !isSaving && !isLoadingHospitals && hospitalsError == nil && !hospitals.isEmpty
  }

  var body: some View {
    CalNavigation {
      Form {
        Section("When") {
          DatePicker("Date", selection: $date, displayedComponents: .date)
        }
        Section("Hospital") {
          if isLoadingHospitals {
            HStack {
              ProgressView()
              Text("Loading hospitals…")
                .foregroundStyle(.secondary)
            }
          } else if let hospitalsError {
            VStack(alignment: .leading, spacing: 8) {
              Text(hospitalsError)
                .font(.caption.weight(.semibold))
                .foregroundStyle(ClinicalPalette.warningText)
              Button("Retry") {
                Task { await reloadHospitals() }
              }
              .font(.caption.weight(.semibold))
            }
          } else if hospitals.isEmpty {
            Text("No hospitals available. Add a hospital in Manage locations.")
              .font(.caption)
              .foregroundStyle(.secondary)
          } else {
            Picker("Hospital", selection: $locationId) {
              ForEach(hospitals) { hospital in
                Text(hospital.displayName).tag(hospital.id)
              }
            }
          }
        }
        Section("Session") {
          Picker("Session", selection: $session) {
            Text("AM").tag("am")
            Text("PM").tag("pm")
            Text("Both").tag("both")
            Text("Custom").tag("custom")
          }
          .pickerStyle(.segmented)
          .onChange(of: session) { value in
            applySessionDefaults(value)
          }
          DatePicker("Start", selection: $startTime, displayedComponents: .hourAndMinute)
          DatePicker("End", selection: $endTime, displayedComponents: .hourAndMinute)
        }
        Section("Notes") {
          TextField("Optional", text: $notes)
        }
        if let errorMessage {
          Section {
            Text(errorMessage)
              .font(.caption.weight(.semibold))
              .foregroundStyle(ClinicalPalette.warningText)
          }
        }
      }
      .navigationTitle("New Block OR")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Close") { dismiss() }
            .disabled(isSaving)
        }
        ToolbarItem(placement: .confirmationAction) {
          Button("Create") {
            Task { await create() }
          }
          .disabled(!canCreate)
        }
      }
      .task {
        guard !didLoad else { return }
        didLoad = true
        date = Calendar.current.startOfDay(for: initialDate)
        applySessionDefaults(session)
        await reloadHospitals()
      }
    }
  }

  private func reloadHospitals() async {
    isLoadingHospitals = true
    hospitalsError = nil
    defer { isLoadingHospitals = false }
    do {
      let meta = try await loadMeta()
      hospitals = meta.hospitals
      if locationId == 0, let first = hospitals.first {
        locationId = first.id
      }
    } catch {
      hospitalsError = error.localizedDescription
    }
  }

  private func applySessionDefaults(_ value: String) {
    switch value {
    case "am":
      startTime = Self.dateForTime("07:00")
      endTime = Self.dateForTime("12:00")
    case "pm":
      startTime = Self.dateForTime("12:00")
      endTime = Self.dateForTime("17:00")
    case "both":
      startTime = Self.dateForTime("07:00")
      endTime = Self.dateForTime("17:00")
    default:
      break
    }
  }

  private func create() async {
    guard canCreate else { return }
    isSaving = true
    errorMessage = nil
    defer { isSaving = false }
    do {
      try await createAction(
        date,
        locationId,
        session,
        Self.hhmm(startTime),
        Self.hhmm(endTime),
        notes
      )
      dismiss()
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  private static func hhmm(_ date: Date) -> String {
    let formatter = DateFormatter()
    formatter.dateFormat = "HH:mm"
    return formatter.string(from: date)
  }

  private static func dateForTime(_ value: String) -> Date {
    let parts = value.split(separator: ":").compactMap { Int($0) }
    var components = Calendar.current.dateComponents([.year, .month, .day], from: Date())
    components.hour = parts.count > 0 ? parts[0] : 7
    components.minute = parts.count > 1 ? parts[1] : 0
    return Calendar.current.date(from: components) ?? Date()
  }
}

private struct SchedulerChangesView: View {
  let changes: [NativeSchedulerChange]

  var body: some View {
    List {
      if changes.isEmpty {
        SchedulerEmptyRow(text: "No changes in the last 24 hours.")
      } else {
        ForEach(changes) { change in
          VStack(alignment: .leading, spacing: 4) {
            HStack {
              Text(change.surgeonInitials.isEmpty ? "CAL" : change.surgeonInitials)
                .font(ClinicalTypography.sectionLabel)
                .foregroundStyle(ClinicalPalette.teal)
              Text(change.title)
                .font(ClinicalTypography.rowTitleStrong)
            }
            Text(change.body)
              .font(.caption)
              .foregroundStyle(.secondary)
            if let date = change.date {
              Text(date)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            }
          }
          .padding(.vertical, 4)
        }
      }
    }
    .background(ScheduleWaterBackground())
  }
}

private struct SchedulerEmptyRow: View {
  let text: String

  var body: some View {
    Text(text)
      .font(ClinicalTypography.rowTitle)
      .foregroundStyle(.secondary)
      .padding(12)
      .frame(maxWidth: .infinity, alignment: .leading)
      .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)
  }
}
