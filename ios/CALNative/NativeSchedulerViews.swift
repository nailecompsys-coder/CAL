import SwiftUI

struct NativeSchedulerShell: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var selectedDate = Date()
  @State private var selectedBlock: NativeSchedulerBlock?
  @State private var selectedTab: SchedulerTab = .blocks

  private enum SchedulerTab: String, CaseIterable, Identifiable {
    case blocks = "Blocks"
    case changes = "Changes"

    var id: String { rawValue }
  }

  private var blockGroups: [SchedulerBlockGroup] {
    Dictionary(grouping: store.schedulerBlocks) { block in
      "\(block.date)|\(block.locationId)|\(block.start)|\(block.end)"
    }
    .map { _, blocks in
      SchedulerBlockGroup(blocks: blocks)
    }
    .sorted { lhs, rhs in
      lhs.sortKey < rhs.sortKey
    }
  }

  private var windowTitle: String {
    let calendar = Calendar.current
    let endDate = calendar.date(byAdding: .day, value: 56, to: selectedDate) ?? selectedDate
    return "\(Self.shortDateFormatter.string(from: selectedDate)) - \(Self.shortDateFormatter.string(from: endDate))"
  }

  var body: some View {
    CalNavigation {
      ZStack {
        ScheduleWaterBackground()
        VStack(spacing: 0) {
          SchedulerDateControl(
            selectedDate: $selectedDate,
            windowTitle: windowTitle,
            jump: jumpDate
          )
          .calReadableColumn(ClinicalLayout.wideColumn)

          Picker("Scheduler", selection: $selectedTab) {
            ForEach(SchedulerTab.allCases) { tab in
              Text(tab.rawValue).tag(tab)
            }
          }
          .pickerStyle(.segmented)
          .padding(.horizontal, 16)
          .padding(.vertical, 10)
          .background(.ultraThinMaterial)
          .calReadableColumn(ClinicalLayout.wideColumn)

          if selectedTab == .blocks {
            SchedulerOpenBlocksView(
              blockGroups: blockGroups,
              statusMessage: store.warningMessage,
              selectBlock: { block in
                selectedBlock = block
                Task { await store.loadSchedulerBlock(block) }
              }
            )
            .calReadableColumn(ClinicalLayout.contentColumn)
          } else {
            SchedulerChangesView(changes: store.schedulerChanges)
              .calReadableColumn(ClinicalLayout.contentColumn)
          }
        }
      }
      .navigationTitle("Scheduler")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .navigationBarLeading) {
          Button("Today") {
            selectedDate = Date()
            Task { await store.loadScheduler(containing: selectedDate) }
          }
        }
        ToolbarItemGroup(placement: .navigationBarTrailing) {
          Button {
            Task { await store.loadScheduler(containing: selectedDate) }
          } label: {
            Image(systemName: "arrow.clockwise")
          }
          Button(role: .destructive) {
            store.logout()
          } label: {
            Image(systemName: "rectangle.portrait.and.arrow.right")
          }
        }
      }
      .sheet(item: $selectedBlock) { block in
        SchedulerAssignSheet(
          block: block,
          detail: store.selectedSchedulerDetail,
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
              store.setWarningMessage(error.localizedDescription)
            }
          },
          updateAction: { assignmentId, surgeon, startTime, caseCount, note in
            do {
              _ = try await store.updateSchedulerAssignment(
                blockId: block.id,
                assignmentId: assignmentId,
                surgeonId: surgeon.surgeonId,
                startTime: startTime,
                caseCount: caseCount,
                note: note
              )
            } catch {
              store.setWarningMessage(error.localizedDescription)
            }
          },
          removeAssignmentAction: { assignmentId in
            do {
              try await store.removeSchedulerAssignment(blockId: block.id, assignmentId: assignmentId)
            } catch {
              store.setWarningMessage(error.localizedDescription)
            }
          },
          clearAction: {
            do {
              try await store.clearSchedulerBlock(blockId: block.id)
              selectedBlock = nil
            } catch {
              store.setWarningMessage(error.localizedDescription)
            }
          }
        )
      }
    }
    .task {
      await store.loadScheduler(containing: selectedDate)
    }
    .onChange(of: selectedDate) { newValue in
      Task { await store.loadScheduler(containing: newValue) }
    }
  }

  private func jumpDate(_ component: Calendar.Component, _ value: Int) {
    selectedDate = Calendar.current.date(byAdding: component, value: value, to: selectedDate) ?? selectedDate
  }

  private static let shortDateFormatter: DateFormatter = {
    let formatter = DateFormatter()
    formatter.dateFormat = "MMM d"
    return formatter
  }()
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

  init(blocks: [NativeSchedulerBlock]) {
    let sortedBlocks = blocks.sorted { lhs, rhs in
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
    self.id = "\(first.date)|\(first.locationId)|\(first.start)|\(first.end)"
  }
}

private struct SchedulerDayGroup: Identifiable {
  let id: String
  let title: String
  let groups: [SchedulerBlockGroup]

  init(groups: [SchedulerBlockGroup]) {
    self.groups = groups
    self.id = groups.first?.date ?? UUID().uuidString
    self.title = groups.first?.displayDate ?? ""
  }
}

private struct SchedulerDateControl: View {
  @Binding var selectedDate: Date
  let windowTitle: String
  let jump: (Calendar.Component, Int) -> Void

  var body: some View {
    VStack(spacing: 8) {
      HStack(spacing: 8) {
        Button {
          jump(.day, -7)
        } label: {
          Image(systemName: "chevron.left")
        }
        .buttonStyle(.bordered)

        DatePicker("Start", selection: $selectedDate, displayedComponents: .date)
          .datePickerStyle(.compact)
          .labelsHidden()
          .frame(maxWidth: .infinity)

        Button {
          jump(.day, 7)
        } label: {
          Image(systemName: "chevron.right")
        }
        .buttonStyle(.bordered)
      }

      jumpControls
    }
    .padding(.horizontal, 16)
    .padding(.top, 10)
    .padding(.bottom, 8)
    .background(.ultraThinMaterial)
  }

  @ViewBuilder
  private var jumpControls: some View {
    if #available(iOS 16.0, *) {
      ViewThatFits(in: .horizontal) {
        jumpRow
        VStack(alignment: .leading, spacing: 8) {
          Text(windowTitle)
            .font(ClinicalTypography.caption)
            .foregroundStyle(.secondary)
          HStack(spacing: 8) {
            jumpButtons
            Spacer(minLength: 0)
          }
        }
      }
    } else {
      jumpRow
    }
  }

  private var jumpRow: some View {
    HStack(spacing: 8) {
      Text(windowTitle)
        .font(ClinicalTypography.caption)
        .foregroundStyle(.secondary)
        .lineLimit(1)
        .minimumScaleFactor(0.85)
      Spacer(minLength: 4)
      jumpButtons
    }
  }

  private var jumpButtons: some View {
    HStack(spacing: 8) {
      Button("+1 mo") {
        jump(.month, 1)
      }
      .font(ClinicalTypography.caption)
      .buttonStyle(.bordered)
      Button("+6 wk") {
        jump(.day, 42)
      }
      .font(ClinicalTypography.caption)
      .buttonStyle(.borderedProminent)
    }
  }
}

private struct SchedulerOpenBlocksView: View {
  let blockGroups: [SchedulerBlockGroup]
  let statusMessage: String?
  let selectBlock: (NativeSchedulerBlock) -> Void

  private var dayGroups: [SchedulerDayGroup] {
    Dictionary(grouping: blockGroups, by: \.date)
      .map { _, groups in
        SchedulerDayGroup(groups: groups.sorted { $0.sortKey < $1.sortKey })
      }
      .sorted { $0.id < $1.id }
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 12) {
        if let statusMessage {
          Label(statusMessage, systemImage: "exclamationmark.triangle")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
        }

        SchedulerSectionTitle("Block OR")
        ForEach(dayGroups) { day in
          VStack(alignment: .leading, spacing: 8) {
            Text(day.title)
              .font(ClinicalTypography.rowTitleStrong)
              .foregroundStyle(ClinicalPalette.ink)
              .padding(.horizontal, 4)

            ForEach(day.groups) { group in
              VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                  Text(group.location)
                    .font(ClinicalTypography.headlineStrong)
                    .foregroundStyle(ClinicalPalette.teal)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                  Text("\(group.start)-\(group.end)")
                    .font(ClinicalTypography.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
                  Spacer(minLength: 0)
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
          }
        }
        if blockGroups.isEmpty {
          SchedulerEmptyRow(text: "No open Block OR time in this window.")
        }
      }
      .padding(16)
    }
  }
}

private struct SchedulerBlockPill: View {
  let block: NativeSchedulerBlock

  var body: some View {
    HStack(alignment: .center, spacing: 10) {
      VStack(alignment: .leading, spacing: 4) {
        if block.assignments.isEmpty {
          Text("Open practice block")
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
    .background(block.isOpen ? Color.white.opacity(0.45) : Color.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
  }
}

private struct SchedulerAssignSheet: View {
  let block: NativeSchedulerBlock
  let detail: NativeSchedulerBlockDetailResponse?
  let isLoading: Bool
  let assignAction: (NativeSchedulerCandidate, String, Int, String) async -> Void
  let updateAction: (Int, NativeSchedulerCandidate, String, Int, String) async -> Void
  let removeAssignmentAction: (Int) async -> Void
  let clearAction: () async -> Void
  @Environment(\.dismiss) private var dismiss
  @State private var mode: SheetMode = .idle
  @State private var editingAssignmentId: Int?
  @State private var selectedCandidate: NativeSchedulerCandidate?
  @State private var startTime: Date = Date()
  @State private var caseCount = 1
  @State private var note = ""
  @State private var showUnavailable = false
  @State private var didSeedDefaults = false
  @State private var isSaving = false

  private enum SheetMode {
    case idle
    case editing
    case adding
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

  private var editingAssignment: NativeSchedulerBlockAssignment? {
    guard let editingAssignmentId else { return nil }
    return assignedRows.first { $0.id == editingAssignmentId }
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

  private var hasDirtyChanges: Bool {
    guard let candidate = selectedCandidate else { return false }
    switch mode {
    case .adding:
      return true
    case .editing:
      guard let current = editingAssignment else { return false }
      return candidate.surgeonId != current.surgeonId
        || currentStartHHMM != current.start
        || caseCount != current.caseCount
        || note != current.note
    case .idle:
      return assignedRows.isEmpty && selectedCandidate != nil
    }
  }

  private var primaryButtonTitle: String {
    guard let candidate = selectedCandidate else { return "Select a surgeon" }
    switch mode {
    case .editing:
      return hasDirtyChanges
        ? "Save \(candidate.initials) · \(currentStartHHMM)"
        : "No changes"
    case .adding, .idle:
      return "Add \(candidate.initials) · \(currentStartHHMM)"
    }
  }

  private var canSave: Bool {
    guard let candidate = selectedCandidate, !isLoading, !isSaving else { return false }
    if !candidate.isClear && note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return false
    }
    return hasDirtyChanges
  }

  var body: some View {
    CalNavigation {
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
              Text("\(liveBlock.displayLocation)  \(liveBlock.start)-\(liveBlock.end)")
                .font(ClinicalTypography.headlineStrong)
                .foregroundStyle(ClinicalPalette.ink)
              Text(liveBlock.displayDate)
                .font(ClinicalTypography.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
            if isLoading || isSaving {
              ProgressView()
            }
          }

          VStack(alignment: .leading, spacing: 8) {
            Text("ON THIS BLOCK")
              .font(ClinicalTypography.sectionLabel)
              .foregroundStyle(.secondary)
            if assignedRows.isEmpty {
              Text("No surgeons yet — pick one below")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
            } else {
              ForEach(assignedRows) { assignment in
                AssignedSurgeonPill(
                  assignment: assignment,
                  isSelected: editingAssignmentId == assignment.id && mode == .editing,
                  isBusy: isLoading || isSaving,
                  onSelect: { beginEditing(assignment) },
                  onRemove: {
                    Task {
                      if editingAssignmentId == assignment.id {
                        resetToIdle()
                      }
                      await removeAssignmentAction(assignment.id)
                    }
                  }
                )
              }
              Text("Tap a row to edit that slot · × removes it")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            }

            if !assignedRows.isEmpty {
              Button {
                beginAdding()
              } label: {
                Label("Add another slot", systemImage: "plus.circle.fill")
                  .font(.subheadline.weight(.bold))
                  .frame(maxWidth: .infinity)
                  .padding(.vertical, 8)
              }
              .buttonStyle(.bordered)
              .tint(ClinicalPalette.teal)
              .disabled(isLoading || isSaving || mode == .adding)
            }
          }
          .padding(12)
          .frame(maxWidth: .infinity, alignment: .leading)
          .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)

          if mode != .idle || assignedRows.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
              Text(mode == .editing ? "EDIT SLOT" : "NEW SLOT")
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
                  .foregroundStyle(ClinicalPalette.amber)
              }
              if mode == .editing, let editing = editingAssignment {
                Text("Editing \(editing.surgeonInitials) at \(editing.start)")
                  .font(.caption2.weight(.semibold))
                  .foregroundStyle(ClinicalPalette.teal)
              }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.tealSoft)

            VStack(alignment: .leading, spacing: 8) {
              Text("PICK SURGEON")
                .font(ClinicalTypography.sectionLabel)
                .foregroundStyle(.secondary)

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
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.cardStrong)

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
              .padding(12)
              .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
            }

            Button {
              Task { await save() }
            } label: {
              Text(primaryButtonTitle)
                .font(.headline.weight(.bold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
            }
            .buttonStyle(.borderedProminent)
            .tint(ClinicalPalette.teal)
            .disabled(!canSave)

            if mode == .editing || mode == .adding {
              Button("Cancel edit") {
                resetToIdle()
              }
              .font(.caption.weight(.bold))
              .frame(maxWidth: .infinity)
              .disabled(isSaving)
            }
          }

          if !assignedRows.isEmpty {
            Button(role: .destructive) {
              Task { await clearAction() }
            } label: {
              Text("Clear entire block")
                .font(.caption.weight(.bold))
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(isLoading || isSaving)
          }
        }
        .padding(16)
      }
      .background(ScheduleWaterBackground())
      .navigationTitle(assignedRows.isEmpty ? "Assign Block" : "Edit Block")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Done") { dismiss() }
        }
      }
      .onAppear {
        seedDefaultsIfNeeded()
      }
      .onChange(of: assignedRows.map(\.id)) { ids in
        if let editingAssignmentId, !ids.contains(editingAssignmentId) {
          resetToIdle()
        } else if mode == .editing, let editing = editingAssignment {
          // Keep form synced after a successful in-place save.
          loadForm(from: editing)
        }
      }
      .onChange(of: detail?.candidates.count ?? 0) { _ in
        seedDefaultsIfNeeded()
      }
    }
  }

  private func seedDefaultsIfNeeded() {
    guard !didSeedDefaults else {
      if mode == .editing, let editing = editingAssignment, selectedCandidate == nil {
        selectedCandidate = candidates.first { $0.surgeonId == editing.surgeonId }
      }
      return
    }
    didSeedDefaults = true
    if assignedRows.isEmpty {
      mode = .adding
      caseCount = 1
      note = ""
      startTime = Self.dateForTime(liveBlock.start)
    } else {
      resetToIdle()
    }
  }

  private func beginEditing(_ assignment: NativeSchedulerBlockAssignment) {
    mode = .editing
    editingAssignmentId = assignment.id
    loadForm(from: assignment)
  }

  private func beginAdding() {
    mode = .adding
    editingAssignmentId = nil
    selectedCandidate = nil
    caseCount = 1
    note = ""
    startTime = Self.suggestedStart(
      blockStart: liveBlock.start,
      blockEnd: liveBlock.end,
      takenStarts: assignedRows.map(\.start)
    )
  }

  private func resetToIdle() {
    mode = assignedRows.isEmpty ? .adding : .idle
    editingAssignmentId = nil
    selectedCandidate = nil
    caseCount = 1
    note = ""
    if assignedRows.isEmpty {
      startTime = Self.dateForTime(liveBlock.start)
    }
  }

  private func loadForm(from assignment: NativeSchedulerBlockAssignment) {
    selectedCandidate = candidates.first { $0.surgeonId == assignment.surgeonId }
    startTime = Self.dateForTime(assignment.start)
    caseCount = max(1, assignment.caseCount)
    note = assignment.note
  }

  private func save() async {
    guard let candidate = selectedCandidate, canSave else { return }
    isSaving = true
    defer { isSaving = false }
    let start = currentStartHHMM
    switch mode {
    case .editing:
      guard let assignmentId = editingAssignmentId else { return }
      await updateAction(assignmentId, candidate, start, caseCount, note)
      if let editing = assignedRows.first(where: { $0.id == assignmentId }) {
        loadForm(from: editing)
      }
    case .adding, .idle:
      await assignAction(candidate, start, caseCount, note)
      resetToIdle()
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
    let hour = calendar.component(.hour, from: latestTaken)
    let next = calendar.date(bySettingHour: hour + 1, minute: 0, second: 0, of: latestTaken)
      ?? calendar.date(byAdding: .hour, value: 1, to: latestTaken)
      ?? start

    if next < start { return start }
    if next >= end {
      let fallback = calendar.date(byAdding: .hour, value: -1, to: end) ?? start
      return max(start, fallback)
    }
    return next
  }
}

private struct AssignedSurgeonPill: View {
  let assignment: NativeSchedulerBlockAssignment
  let isSelected: Bool
  let isBusy: Bool
  let onSelect: () -> Void
  let onRemove: () -> Void

  var body: some View {
    HStack(spacing: 8) {
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
            Text("\(assignment.start) · \(assignment.caseCount) case\(assignment.caseCount == 1 ? "" : "s")")
              .font(ClinicalTypography.caption)
              .foregroundStyle(.secondary)
          }
          Spacer(minLength: 0)
          if isSelected {
            Text("Editing")
              .font(ClinicalTypography.badge)
              .foregroundStyle(ClinicalPalette.teal)
          }
        }
      }
      .buttonStyle(.plain)
      .disabled(isBusy)

      Button(role: .destructive, action: onRemove) {
        Image(systemName: "xmark.circle.fill")
          .font(.title3)
          .foregroundStyle(.red.opacity(0.85))
      }
      .buttonStyle(.plain)
      .disabled(isBusy)
      .accessibilityLabel("Remove \(assignment.surgeonInitials)")
    }
    .padding(.horizontal, 10)
    .padding(.vertical, 8)
    .background(
      isSelected ? ClinicalPalette.teal.opacity(0.12) : Color.white.opacity(0.7),
      in: RoundedRectangle(cornerRadius: 12, style: .continuous)
    )
    .overlay(
      RoundedRectangle(cornerRadius: 12, style: .continuous)
        .stroke(isSelected ? ClinicalPalette.teal.opacity(0.5) : Color.clear, lineWidth: 1.5)
    )
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

private struct SchedulerSectionTitle: View {
  let text: String

  init(_ text: String) {
    self.text = text
  }

  var body: some View {
    Text(text.uppercased())
      .font(ClinicalTypography.sectionLabel)
      .foregroundStyle(.secondary)
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
