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

// MARK: - Call Builder (phone: day list + tap sheet; local draft until publish API)

private enum CallBuilderGroup: String, CaseIterable, Identifiable {
  case wg = "WG"
  case alt = "ALT"
  var id: String { rawValue }
  var title: String { "\(rawValue) Group" }
  var groupId: Int { self == .wg ? 1 : 2 }
}

struct CallBuilderHomeView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection
  @State private var month = CallBuilderHomeView.defaultMonth()
  /// "day|groupId" → surgeon id
  @State private var draft: [String: Int] = [:]
  @State private var picking: CallBuilderPick?

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

            Text("Tap a WG or ALT slot, then pick a surgeon. Draft stays on this phone until Publish is deployed.")
              .font(.caption)
              .foregroundStyle(.secondary)

            ForEach(daysInMonth, id: \.self) { day in
              CallBuilderDayRow(
                day: day,
                wg: chip(day: day, group: .wg),
                alt: chip(day: day, group: .alt),
                onTap: { group in picking = CallBuilderPick(day: day, group: group) }
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
          Button("Publish") {
            // Preview / local draft only until native publish ships.
          }
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(ClinicalPalette.teal)
          .disabled(draft.isEmpty)
        }
      }
      .sheet(item: $picking) { pick in
        CallBuilderPickerSheet(
          pick: pick,
          roster: roster,
          draftCount: { sid in draft.values.filter { $0 == sid }.count },
          onPick: { surgeonId in
            let key = Self.key(day: pick.day, group: pick.group)
            if let surgeonId {
              draft[key] = surgeonId
            } else {
              draft.removeValue(forKey: key)
            }
            picking = nil
          },
          onCancel: { picking = nil }
        )
      }
    }
  }

  private func chip(day: Date, group: CallBuilderGroup) -> (initials: String, flagged: Bool)? {
    guard let id = draft[Self.key(day: day, group: group)] else { return nil }
    let surg = roster.first { $0.id == id }
    return (surg?.initials ?? "?", false)
  }

  private func shiftMonth(_ delta: Int) {
    if let next = Calendar.current.date(byAdding: .month, value: delta, to: month) {
      month = next
    }
  }

  private static func key(day: Date, group: CallBuilderGroup) -> String {
    let d = day.formatted(.iso8601.year().month().day())
    return "\(d)|\(group.groupId)"
  }

  private static func defaultMonth() -> Date {
    // Prefer December 2026 while building the first empty month; else current month.
    var c = DateComponents()
    c.year = 2026
    c.month = 12
    c.day = 1
    return Calendar.current.date(from: c) ?? Date()
  }
}

private struct CallBuilderPick: Identifiable {
  let day: Date
  let group: CallBuilderGroup
  var id: String { "\(day.timeIntervalSince1970)-\(group.rawValue)" }
}

private struct CallBuilderDayRow: View {
  let day: Date
  let wg: (initials: String, flagged: Bool)?
  let alt: (initials: String, flagged: Bool)?
  let onTap: (CallBuilderGroup) -> Void

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

      CallBuilderSlot(label: "WG Group", chip: wg) { onTap(.wg) }
      CallBuilderSlot(label: "ALT Group", chip: alt) { onTap(.alt) }
    }
    .padding(.vertical, 4)
  }
}

private struct CallBuilderSlot: View {
  let label: String
  let chip: (initials: String, flagged: Bool)?
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
        RoundedRectangle(cornerRadius: 10, style: .continuous)
          .stroke(chip == nil ? ClinicalPalette.stroke.opacity(0.7) : ClinicalPalette.teal.opacity(0.55), style: StrokeStyle(lineWidth: 1, dash: chip == nil ? [4, 3] : []))
      }
    }
    .buttonStyle(.plain)
  }
}

private struct CallBuilderPickerSheet: View {
  let pick: CallBuilderPick
  let roster: [NativeSurgeon]
  let draftCount: (Int) -> Int
  let onPick: (Int?) -> Void
  let onCancel: () -> Void

  var body: some View {
    CalNavigation {
      List {
        Section {
          Text(pick.day.formatted(.dateTime.weekday(.wide).month().day()) + " · " + pick.group.title)
            .font(.subheadline)
            .foregroundStyle(.secondary)
        }
        Section("Surgeons · practice rank") {
          ForEach(roster) { s in
            Button {
              onPick(s.id)
            } label: {
              HStack {
                VStack(alignment: .leading, spacing: 2) {
                  Text(s.name)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(ClinicalPalette.ink)
                  Text("Draft \(draftCount(s.id))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                Spacer()
                Text(s.initials)
                  .font(.subheadline.weight(.bold))
                  .foregroundStyle(ClinicalPalette.teal)
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
