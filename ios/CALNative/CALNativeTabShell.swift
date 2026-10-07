import SwiftUI

struct CALNativeTabShell: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var selectedSection: CALNativeSection = .schedule
  @State private var sharedFocusDate = Date()

  var body: some View {
    Group {
      switch selectedSection {
      case .schedule:
        ScheduleHomeView(
          store: store,
          selectedSection: $selectedSection,
          selectedDate: $sharedFocusDate
        )
      case .timeOff:
        TimeOffHomeView(store: store, selectedSection: $selectedSection)
      case .callBuilder:
        CallBuilderHomeView(store: store, selectedSection: $selectedSection)
      }
    }
    .tint(ClinicalPalette.teal)
  }
}

struct NativeAlertsToolbarButton: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var showingAlerts = false

  private var unreadCount: Int { store.alerts.unreadCount }

  var body: some View {
    Button {
      showingAlerts = true
    } label: {
      ZStack(alignment: .topTrailing) {
        Image(systemName: unreadCount > 0 ? "bell.badge" : "bell")
          .font(.body.weight(.semibold))
          .foregroundStyle(unreadCount > 0 ? ClinicalPalette.teal : ClinicalPalette.ink)
          .frame(width: 28, height: 28)

        if unreadCount > 0 {
          Text(unreadCount > 9 ? "9+" : "\(unreadCount)")
            .font(ClinicalTypography.badge)
            .foregroundStyle(.white)
            .padding(.horizontal, 4)
            .padding(.vertical, 1)
            .background(ClinicalPalette.teal, in: Capsule())
            .offset(x: 8, y: -6)
        }
      }
      .frame(width: 34, height: 34)
      .contentShape(Rectangle())
    }
    .accessibilityLabel(unreadCount > 0 ? "Alerts, \(unreadCount) unread" : "Alerts")
    .sheet(isPresented: $showingAlerts) {
      NativeAlertInbox(alerts: store.alerts.recent, markRead: {
        showingAlerts = false
        Task {
          await store.markAlertsRead()
        }
      })
    }
  }
}

private struct NativeAlertInbox: View {
  let alerts: [NativeScheduleAlert]
  let markRead: () -> Void
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    CalNavigation {
      List {
        if alerts.isEmpty {
          Label("No CAL alerts", systemImage: "bell.slash")
            .foregroundStyle(.secondary)
        } else {
          ForEach(alerts) { alert in
            VStack(alignment: .leading, spacing: 5) {
              HStack(alignment: .firstTextBaseline) {
                Text(alert.title)
                  .font(.subheadline.weight(alert.isRead ? .semibold : .bold))
                Spacer()
                if !alert.displayTime.isEmpty {
                  Text(alert.displayTime)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
              }
              Text(alert.body)
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            .padding(.vertical, 4)
          }
        }
      }
      .navigationTitle("CAL Alerts")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Close") {
            dismiss()
          }
        }
        ToolbarItem(placement: .confirmationAction) {
          Button("Mark Read") {
            markRead()
            dismiss()
          }
          .disabled(alerts.allSatisfy(\.isRead))
        }
      }
    }
  }
}

enum CALNativeSection: String, CaseIterable, Identifiable {
  case schedule = "Calendar"
  case timeOff = "Time Off"
  case callBuilder = "Call Builder"

  var id: String { rawValue }

  var systemImage: String {
    switch self {
    case .schedule:
      return "calendar"
    case .timeOff:
      return "person.crop.circle.badge.minus"
    case .callBuilder:
      return "square.grid.2x2"
    }
  }

  static func menuCases(showsCallBuilder: Bool) -> [CALNativeSection] {
    allCases.filter { $0 != .callBuilder || showsCallBuilder }
  }
}

struct CALNativeSectionMenu: View {
  @Binding var selectedSection: CALNativeSection
  let store: NativeScheduleStore

  var body: some View {
    Menu {
      ForEach(CALNativeSection.menuCases(showsCallBuilder: store.showsCallBuilder)) { section in
        Button {
          selectedSection = section
        } label: {
          Label(section.rawValue, systemImage: section.systemImage)
        }
      }

      if store.canSwitchModes {
        Divider()
        Button {
          Task { await store.switchSessionRole(to: .scheduler) }
        } label: {
          Label("Switch to Scheduler", systemImage: "calendar.badge.clock")
        }
      }

      Divider()

      Button(role: .destructive) {
        store.logout()
      } label: {
        Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
      }
    } label: {
      Image(systemName: "line.3.horizontal.circle")
    }
  }
}

struct CALNativeTitleMenu: View {
  @Binding var selectedSection: CALNativeSection
  let store: NativeScheduleStore

  var body: some View {
    Menu {
      ForEach(CALNativeSection.menuCases(showsCallBuilder: store.showsCallBuilder)) { section in
        Button {
          selectedSection = section
        } label: {
          Label(section.rawValue, systemImage: section.systemImage)
        }
      }

      if store.canSwitchModes {
        Divider()
        Button {
          Task { await store.switchSessionRole(to: .scheduler) }
        } label: {
          Label("Switch to Scheduler", systemImage: "calendar.badge.clock")
        }
      }

      Divider()

      if store.isSupportPreview {
        Label("Read-only · \(store.supportPreviewSurgeonName ?? "Surgeon")", systemImage: "eye")
        Button(role: .destructive) {
          store.logout()
        } label: {
          Label("Exit Preview", systemImage: "rectangle.portrait.and.arrow.right")
        }
      } else {
        Button(role: .destructive) {
          store.logout()
        } label: {
          Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
        }
      }
    } label: {
      HStack(spacing: 4) {
        if store.isSupportPreview {
          Image(systemName: "eye")
            .accessibilityHidden(true)
        }
        Text(selectedSection.rawValue)
          .font(ClinicalTypography.headline)
        Image(systemName: "chevron.down")
          .font(ClinicalTypography.badge)
      }
      .foregroundStyle(.primary)
    }
    .accessibilityLabel(store.isSupportPreview ? "\(selectedSection.rawValue), read-only preview" : selectedSection.rawValue)
  }
}

// MARK: - Call Builder (phone: day list + tap sheet; draft saved server-side until publish)

private struct CallBuilderChip: Equatable {
  let initials: String
  let flagged: Bool
  let source: String // draft | live
  var isDraft: Bool { source == "draft" }
}

struct CallBuilderHomeView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection
  @State private var month = CallBuilderHomeView.defaultMonth()
  @State private var cellsByKey: [String: NativeCallBuilderCell] = [:]
  @State private var groups: [NativeCallBuilderGroup] = []
  @State private var draftCount = 0
  @State private var picking: CallBuilderPick?
  @State private var loadBySurgeon: [Int: NativeCallBuilderLoad] = [:]
  @State private var loadLegend = "YTD calls/wknd · month calls/wknd · holidays/last"
  @State private var saveError: String?
  @State private var isSaving = false

  private var roster: [NativeSurgeon] {
    store.surgeons
      .filter { $0.staffType == "physician" }
      .sorted {
        ($0.sortOrder ?? Int.max, $0.name) < ($1.sortOrder ?? Int.max, $1.name)
      }
  }

  private var daysInMonth: [Date] {
    let cal = Calendar.current
    guard let range = cal.range(of: .day, in: .month, for: month) else { return [] }
    return range.compactMap { day in
      cal.date(from: DateComponents(year: cal.component(.year, from: month), month: cal.component(.month, from: month), day: day))
    }
  }

  private var wgGroup: NativeCallBuilderGroup? {
    groups.first { $0.short == "WG" } ?? groups.first
  }

  private var altGroup: NativeCallBuilderGroup? {
    groups.first { $0.short == "ALT" } ?? groups.dropFirst().first
  }

  var body: some View {
    CalNavigation {
      ZStack {
        ScheduleWaterBackground()
        ScrollView {
          VStack(alignment: .leading, spacing: 12) {
            HStack {
              Button { shiftMonth(-1) } label: {
                Image(systemName: "chevron.left")
              }
              Spacer()
              Text(month.formatted(.dateTime.month(.wide).year()))
                .font(ClinicalTypography.headline)
              Spacer()
              Button { shiftMonth(1) } label: {
                Image(systemName: "chevron.right")
              }
            }
            .foregroundStyle(ClinicalPalette.teal)

            Text(store.isSupportPreview
                 ? "Read-only preview. Sign in as Chris or Amy to save drafts."
                 : "Tap a WG or ALT slot, then pick a surgeon. Drafts save to the server (same as portal) until Publish.")
              .font(.caption)
              .foregroundStyle(.secondary)

            if draftCount > 0 {
              Text("\(draftCount) draft cell\(draftCount == 1 ? "" : "s") saved · publish from portal")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(ClinicalPalette.teal)
            }

            Text(loadLegend)
              .font(.caption2)
              .foregroundStyle(ClinicalPalette.muted)

            if let saveError {
              Text(saveError)
                .font(.caption)
                .foregroundStyle(.red)
            }

            ForEach(daysInMonth, id: \.self) { day in
              CallBuilderDayRow(
                day: day,
                wg: chip(day: day, group: wgGroup),
                alt: chip(day: day, group: altGroup),
                onTap: { short in
                  guard let group = groups.first(where: { $0.short == short }) ?? (short == "WG" ? wgGroup : altGroup) else { return }
                  if store.isSupportPreview { return }
                  picking = CallBuilderPick(day: day, group: group)
                }
              )
            }
          }
          .padding(16)
        }
      }
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .principal) {
          CALNativeTitleMenu(selectedSection: $selectedSection, store: store)
        }
        ToolbarItem(placement: .topBarTrailing) {
          if isSaving {
            ProgressView()
          } else {
            Text(draftCount > 0 ? "Saved" : "")
              .font(.caption.weight(.semibold))
              .foregroundStyle(ClinicalPalette.muted)
          }
        }
      }
      .task(id: monthKey) {
        await reloadBoard()
      }
      .sheet(item: $picking) { pick in
        CallBuilderPickerSheet(
          pick: pick,
          roster: roster,
          loadBySurgeon: loadBySurgeon,
          legend: loadLegend,
          monthLabel: month.formatted(.dateTime.month(.abbreviated)),
          onPick: { surgeonId in
            Task { await applyPick(pick: pick, surgeonId: surgeonId) }
          },
          onCancel: { picking = nil }
        )
      }
    }
  }

  private var monthKey: String {
    let cal = Calendar.current
    return String(format: "%04d-%02d", cal.component(.year, from: month), cal.component(.month, from: month))
  }

  private func reloadBoard() async {
    do {
      let response = try await store.fetchCallBuilderMonth(month: month)
      loadLegend = response.legend
      loadBySurgeon = Dictionary(uniqueKeysWithValues: response.history.map { ($0.surgeonId, $0) })
      groups = response.groups
      cellsByKey = Dictionary(uniqueKeysWithValues: response.cells.map { ($0.key, $0) })
      draftCount = response.draftCount ?? response.cells.filter(\.isDraft).count
      saveError = nil
    } catch {
      saveError = "Could not load Call Builder board."
    }
  }

  private func applyPick(pick: CallBuilderPick, surgeonId: Int?) async {
    picking = nil
    isSaving = true
    defer { isSaving = false }
    do {
      if let surgeonId {
        try await store.placeCallBuilderDraft(
          date: pick.day, callGroupId: pick.group.id, surgeonId: surgeonId
        )
      } else {
        try await store.clearCallBuilderDraft(date: pick.day, callGroupId: pick.group.id)
      }
      await reloadBoard()
    } catch {
      saveError = (error as? LocalizedError)?.errorDescription ?? "Could not save draft."
    }
  }

  private func chip(day: Date, group: NativeCallBuilderGroup?) -> CallBuilderChip? {
    guard let group else { return nil }
    let key = Self.key(day: day, groupId: group.id)
    guard let cell = cellsByKey[key], cell.hasAssignment else { return nil }
    let initials = cell.initials.isEmpty ? "?" : cell.initials
    return CallBuilderChip(initials: initials, flagged: !cell.flag.isEmpty, source: cell.source)
  }

  private func shiftMonth(_ delta: Int) {
    if let next = Calendar.current.date(byAdding: .month, value: delta, to: month) {
      month = next
    }
  }

  private static func key(day: Date, groupId: Int) -> String {
    let d = day.formatted(.iso8601.year().month().day())
    return "\(d)|\(groupId)"
  }

  private static func defaultMonth() -> Date {
    let cal = Calendar.current
    let parts = cal.dateComponents([.year, .month], from: Date())
    return cal.date(from: DateComponents(year: parts.year, month: parts.month, day: 1)) ?? Date()
  }
}

private struct CallBuilderPick: Identifiable {
  let day: Date
  let group: NativeCallBuilderGroup
  var id: String { "\(day.timeIntervalSince1970)-\(group.id)" }
}

private struct CallBuilderDayRow: View {
  let day: Date
  let wg: CallBuilderChip?
  let alt: CallBuilderChip?
  let onTap: (String) -> Void

  private var isWeekend: Bool {
    let w = Calendar.current.component(.weekday, from: day)
    return w == 1 || w == 7
  }

  var body: some View {
    HStack(alignment: .center, spacing: 10) {
      VStack(alignment: .leading, spacing: 2) {
        Text(day.formatted(.dateTime.weekday(.abbreviated)))
          .font(.caption2)
          .foregroundStyle(.secondary)
        Text(day.formatted(.dateTime.day()))
          .font(.title3.weight(.semibold))
          .foregroundStyle(isWeekend ? ClinicalPalette.teal : ClinicalPalette.ink)
      }
      .frame(width: 44, alignment: .leading)

      CallBuilderSlot(label: "WG Group", chip: wg) { onTap("WG") }
      CallBuilderSlot(label: "ALT Group", chip: alt) { onTap("ALT") }
    }
    .padding(.vertical, 4)
  }
}

private struct CallBuilderSlot: View {
  let label: String
  let chip: CallBuilderChip?
  let action: () -> Void

  var body: some View {
    Button(action: action) {
      VStack(alignment: .leading, spacing: 2) {
        Text(label)
          .font(.caption2)
          .foregroundStyle(.secondary)
        if let chip {
          Text(chip.initials)
            .font(.subheadline.weight(.bold))
            .foregroundStyle(chip.flagged ? ClinicalPalette.muted : ClinicalPalette.ink)
        } else {
          Text("Tap to assign")
            .font(.caption)
            .foregroundStyle(ClinicalPalette.muted)
        }
      }
      .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
      .padding(.horizontal, 10)
      .padding(.vertical, 6)
      .background(ClinicalPalette.card, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      .overlay {
        let dashed = chip == nil || chip?.isDraft == true
        RoundedRectangle(cornerRadius: 10, style: .continuous)
          .stroke(
            chip == nil ? ClinicalPalette.stroke.opacity(0.7) : ClinicalPalette.teal.opacity(0.55),
            style: StrokeStyle(lineWidth: 1, dash: dashed ? [4, 3] : [])
          )
      }
    }
    .buttonStyle(.plain)
  }
}

private struct CallBuilderPickerSheet: View {
  let pick: CallBuilderPick
  let roster: [NativeSurgeon]
  let loadBySurgeon: [Int: NativeCallBuilderLoad]
  let legend: String
  let monthLabel: String
  let onPick: (Int?) -> Void
  let onCancel: () -> Void
  @State private var detailLoad: NativeCallBuilderLoad?

  var body: some View {
    CalNavigation {
      List {
        Section {
          Text(pick.day.formatted(.dateTime.weekday(.wide).month().day()) + " · " + pick.group.short + " Group")
            .font(.subheadline)
            .foregroundStyle(.secondary)
          Text(legend)
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        if let load = detailLoad {
          Section("\(load.firstName) \(load.lastName)") {
            CallBuilderDetailRow(label: "YTD", value: load.detailYTD)
            CallBuilderDetailRow(label: monthLabel, value: load.detailMonth)
            CallBuilderDetailRow(label: "Holidays", value: load.detailHolidays)
            CallBuilderDetailRow(label: "Last holiday", value: load.lastHoliday.isEmpty ? "—" : load.lastHoliday)
            Button("Hide detail") { detailLoad = nil }
          }
        }
        Section("Surgeons · practice rank") {
          ForEach(roster) { s in
            HStack(spacing: 10) {
              Button {
                onPick(s.id)
              } label: {
                HStack {
                  VStack(alignment: .leading, spacing: 2) {
                    Text(s.name)
                      .font(.body.weight(.semibold))
                      .foregroundStyle(ClinicalPalette.ink)
                    Text(loadBySurgeon[s.id]?.loadLine ?? "—/— · —/— · —/—")
                      .font(.caption.monospacedDigit())
                      .foregroundStyle(.secondary)
                  }
                  Spacer()
                  Text(s.initials)
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(ClinicalPalette.teal)
                }
              }
              .buttonStyle(.plain)
              if let load = loadBySurgeon[s.id] {
                Button {
                  detailLoad = load
                } label: {
                  Image(systemName: "info.circle")
                    .foregroundStyle(ClinicalPalette.teal)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Call load detail")
              }
            }
          }
          Button("Clear this day", role: .destructive) {
            onPick(nil)
          }
        }
      }
      .navigationTitle("Assign call")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel", action: onCancel)
        }
      }
    }
  }
}

private struct CallBuilderDetailRow: View {
  let label: String
  let value: String

  var body: some View {
    HStack(alignment: .top) {
      Text(label)
        .foregroundStyle(.secondary)
      Spacer(minLength: 12)
      Text(value)
        .multilineTextAlignment(.trailing)
        .font(.body.monospacedDigit())
    }
  }
}
