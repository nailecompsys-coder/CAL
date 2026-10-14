import SwiftUI

struct CALNativeTabShell: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var selectedSection: CALNativeSection = Self.launchSection()
  @State private var sharedFocusDate = Self.launchDate()

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

  /// Simulator-only: `--cal-section=Call Builder` opens that title-menu section on launch.
  private static func launchSection() -> CALNativeSection {
    #if targetEnvironment(simulator)
    if let arg = CommandLine.arguments.first(where: { $0.hasPrefix("--cal-section=") }) {
      let raw = String(arg.dropFirst("--cal-section=".count))
        .replacingOccurrences(of: "+", with: " ")
      if let section = CALNativeSection(rawValue: raw) {
        return section
      }
    }
    #endif
    return .schedule
  }

  /// Simulator-only: `--cal-date=yyyy-MM-dd` focuses the home calendar on that day.
  private static func launchDate() -> Date {
    #if targetEnvironment(simulator)
    guard let arg = CommandLine.arguments.first(where: { $0.hasPrefix("--cal-date=") }) else {
      return Date()
    }
    let raw = String(arg.dropFirst("--cal-date=".count))
    let formatter = DateFormatter()
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = Calendar.current.timeZone
    formatter.dateFormat = "yyyy-MM-dd"
    return formatter.date(from: raw) ?? Date()
    #else
    return Date()
    #endif
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

// MARK: - Call Builder (phone: view-only month grid; edit + publish in portal)

private struct CallBuilderChip: Equatable {
  let initials: String
  let flagged: Bool
  let source: String // draft | live
  var isDraft: Bool { source == "draft" }
}

private struct CallBuilderMonthCell: Identifiable {
  let id: String
  let date: Date
  let isCurrentMonth: Bool
  let isToday: Bool
  let holiday: String
  let wg: CallBuilderChip?
  let alt: CallBuilderChip?

  var holidayEmoji: String {
    CallBuilderHomeView.holidayEmoji(holiday)
  }
}

struct CallBuilderHomeView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection
  @State private var month = CallBuilderHomeView.defaultMonth()
  @State private var cellsByKey: [String: NativeCallBuilderCell] = [:]
  @State private var groups: [NativeCallBuilderGroup] = []
  @State private var selectedDate = Date()
  @State private var loadError: String?

  private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 7)

  private var wgGroup: NativeCallBuilderGroup? {
    groups.first { $0.short == "WG" } ?? groups.first
  }

  private var altGroup: NativeCallBuilderGroup? {
    groups.first { $0.short == "ALT" } ?? groups.dropFirst().first
  }

  private var monthCells: [CallBuilderMonthCell] {
    let cal = Calendar.current
    guard
      let monthStart = cal.date(from: cal.dateComponents([.year, .month], from: month)),
      let dayRange = cal.range(of: .day, in: .month, for: monthStart)
    else { return [] }

    let weekday = cal.component(.weekday, from: monthStart)
    let padStart = (weekday - cal.firstWeekday + 7) % 7
    let total = padStart + dayRange.count
    let padEnd = (7 - (total % 7)) % 7
    let gridStart = cal.date(byAdding: .day, value: -padStart, to: monthStart) ?? monthStart

    return (0..<(total + padEnd)).compactMap { offset in
      guard let date = cal.date(byAdding: .day, value: offset, to: gridStart) else { return nil }
      let inMonth = cal.isDate(date, equalTo: monthStart, toGranularity: .month)
      return CallBuilderMonthCell(
        id: date.formatted(.iso8601.year().month().day()),
        date: date,
        isCurrentMonth: inMonth,
        isToday: cal.isDateInToday(date),
        holiday: inMonth ? holidayName(day: date) : "",
        wg: inMonth ? chip(day: date, group: wgGroup) : nil,
        alt: inMonth ? chip(day: date, group: altGroup) : nil
      )
    }
  }

  private var selectedCell: CallBuilderMonthCell? {
    monthCells.first { Calendar.current.isDate($0.date, inSameDayAs: selectedDate) && $0.isCurrentMonth }
  }

  var body: some View {
    CalNavigation {
      ZStack {
        ScheduleWaterBackground()
        ScrollView {
          VStack(alignment: .leading, spacing: 10) {
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

            if let loadError {
              Text(loadError)
                .font(.caption)
                .foregroundStyle(.red)
            }

            HStack(spacing: 6) {
              Text("WG")
                .foregroundStyle(ClinicalPalette.site("WG"))
              Text("·")
                .foregroundStyle(.secondary)
              Text("ALT")
                .foregroundStyle(ClinicalPalette.site("AL"))
            }
            .font(.caption2.weight(.bold))
            .frame(maxWidth: .infinity, alignment: .trailing)

            LazyVGrid(columns: columns, spacing: 5) {
              ForEach(Calendar.current.shortWeekdaySymbols, id: \.self) { day in
                Text(String(day.prefix(1)))
                  .font(.caption2.weight(.bold))
                  .foregroundStyle(.secondary)
                  .frame(maxWidth: .infinity)
              }

              ForEach(monthCells) { cell in
                CallBuilderMonthDayCell(
                  cell: cell,
                  isSelected: Calendar.current.isDate(cell.date, inSameDayAs: selectedDate)
                ) {
                  withAnimation(.easeInOut(duration: 0.15)) {
                    selectedDate = cell.date
                  }
                }
              }
            }

            if let selectedCell, selectedCell.isCurrentMonth {
              CallBuilderSelectedDay(cell: selectedCell)
            }
          }
          .padding(.horizontal, 16)
          .padding(.vertical, 10)
        }
      }
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .principal) {
          CALNativeTitleMenu(selectedSection: $selectedSection, store: store)
        }
      }
      .task(id: monthKey) {
        await reloadBoard()
      }
      .onChange(of: monthKey) { _ in
        let cal = Calendar.current
        if !cal.isDate(selectedDate, equalTo: month, toGranularity: .month) {
          selectedDate = month
        }
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
      groups = response.groups
      cellsByKey = Dictionary(uniqueKeysWithValues: response.cells.map { ($0.key, $0) })
      loadError = nil
    } catch {
      loadError = "Could not load Call Builder board."
    }
  }

  private func chip(day: Date, group: NativeCallBuilderGroup?) -> CallBuilderChip? {
    guard let group else { return nil }
    let key = Self.key(day: day, groupId: group.id)
    guard let cell = cellsByKey[key], cell.hasAssignment else { return nil }
    let initials = cell.initials.isEmpty ? "?" : cell.initials
    return CallBuilderChip(initials: initials, flagged: !cell.flag.isEmpty, source: cell.source)
  }

  private func holidayName(day: Date) -> String {
    if let group = wgGroup {
      let key = Self.key(day: day, groupId: group.id)
      if let name = cellsByKey[key]?.holiday, !name.isEmpty { return name }
    }
    if let group = altGroup {
      let key = Self.key(day: day, groupId: group.id)
      if let name = cellsByKey[key]?.holiday, !name.isEmpty { return name }
    }
    return ""
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

  /// Apple emoji for tracked Call Builder holidays (phone month grid).
  static func holidayEmoji(_ name: String) -> String {
    switch name {
    case "Memorial Day": return "🇺🇸"
    case "July 4th": return "🎆"
    case "Labor Day": return "🛠️"
    case "Halloween": return "🎃"
    case "Thanksgiving": return "🦃"
    case "Christmas Eve": return "🍬"
    case "Christmas": return "🎄"
    case "New Year's Eve": return "🥂"
    case "New Year's Day", "New Year's": return "🎉"
    default: return name.isEmpty ? "" : "📅"
    }
  }
}

private struct CallBuilderMonthDayCell: View {
  let cell: CallBuilderMonthCell
  let isSelected: Bool
  let selectAction: () -> Void

  var body: some View {
    Button(action: selectAction) {
      VStack(spacing: 4) {
        Text(cell.date.formatted(.dateTime.day()))
          .font(.caption.weight(cell.isToday || isSelected ? .bold : .semibold))
          .foregroundStyle(cell.isToday ? ClinicalPalette.teal : ClinicalPalette.ink)

        Text(cell.holidayEmoji.isEmpty ? " " : cell.holidayEmoji)
          .font(.body)
          .foregroundStyle(cell.holidayEmoji.isEmpty ? .clear : ClinicalPalette.ink)
          .lineLimit(1)

        HStack(spacing: 2) {
          callText(cell.wg, site: "WG")
          callText(cell.alt, site: "AL")
        }
        Spacer(minLength: 0)
      }
      .padding(.horizontal, 3)
      .padding(.vertical, 10)
      .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
      .opacity(cell.isCurrentMonth ? 1 : 0.35)
      .background(ClinicalPalette.card, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      .overlay {
        RoundedRectangle(cornerRadius: 10, style: .continuous)
          .stroke(
            isSelected ? ClinicalPalette.teal : (hasDraft ? ClinicalPalette.teal.opacity(0.45) : Color.clear),
            style: StrokeStyle(lineWidth: isSelected ? 1.5 : 1, dash: hasDraft && !isSelected ? [3, 2] : [])
          )
      }
    }
    .buttonStyle(.plain)
    .disabled(!cell.isCurrentMonth)
  }

  private var hasDraft: Bool {
    cell.wg?.isDraft == true || cell.alt?.isDraft == true
  }

  @ViewBuilder
  private func callText(_ chip: CallBuilderChip?, site: String) -> some View {
    let siteColor = ClinicalPalette.site(site)
    Text(chip?.initials ?? "·")
      .font(.system(.caption2, design: .monospaced).weight(chip == nil ? .regular : .bold))
      .foregroundStyle(
        chip == nil
          ? ClinicalPalette.muted.opacity(0.45)
          : (chip?.flagged == true ? ClinicalPalette.muted : siteColor)
      )
      .lineLimit(1)
      .minimumScaleFactor(0.6)
      .frame(maxWidth: .infinity)
  }
}

private struct CallBuilderSelectedDay: View {
  let cell: CallBuilderMonthCell

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack(spacing: 12) {
        Text(cell.date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()))
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(ClinicalPalette.ink)
        if !cell.holiday.isEmpty {
          Text("\(cell.holidayEmoji) \(cell.holiday)")
            .font(.caption.weight(.semibold))
            .foregroundStyle(ClinicalPalette.ink)
        }
        Spacer(minLength: 0)
      }
      HStack(spacing: 14) {
        Text("WG \(cell.wg?.initials ?? "—")")
          .font(.system(.caption, design: .monospaced).weight(.bold))
          .foregroundStyle(ClinicalPalette.site("WG"))
        Text("ALT \(cell.alt?.initials ?? "—")")
          .font(.system(.caption, design: .monospaced).weight(.bold))
          .foregroundStyle(ClinicalPalette.site("AL"))
        Spacer(minLength: 0)
      }
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 10)
    .background(ClinicalPalette.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
  }
}
