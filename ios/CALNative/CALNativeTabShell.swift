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
  case schedule = "Schedule"
  case timeOff = "Time Off"

  var id: String { rawValue }

  var systemImage: String {
    switch self {
    case .schedule:
      return "calendar"
    case .timeOff:
      return "person.crop.circle.badge.minus"
    }
  }
}

struct CALNativeSectionMenu: View {
  @Binding var selectedSection: CALNativeSection
  let store: NativeScheduleStore

  var body: some View {
    Menu {
      ForEach(CALNativeSection.allCases) { section in
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
      ForEach(CALNativeSection.allCases) { section in
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
      HStack(spacing: 4) {
        Text(selectedSection.rawValue)
          .font(ClinicalTypography.headline)
        Image(systemName: "chevron.down")
          .font(ClinicalTypography.badge)
      }
      .foregroundStyle(.primary)
    }
  }
}
