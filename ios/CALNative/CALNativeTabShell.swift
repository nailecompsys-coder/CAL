import SwiftUI

struct CALNativeTabShell: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var selectedSection: CALNativeSection = .schedule
  @State private var sharedFocusDate = Date()
  @State private var showingAlerts = false

  private var latestUnreadAlert: NativeScheduleAlert? {
    store.alerts.recent.first { !$0.isRead } ?? store.alerts.recent.first
  }

  var body: some View {
    ZStack(alignment: .top) {
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
        case .patients:
          PatientScheduleView(
            store: store,
            selectedSection: $selectedSection,
            selectedDate: $sharedFocusDate
          )
        }
      }

      if store.alerts.unreadCount > 0, let alert = latestUnreadAlert {
        NativeAlertBanner(alert: alert, unreadCount: store.alerts.unreadCount) {
          showingAlerts = true
        }
        .padding(.horizontal, 14)
        .padding(.top, 54)
        .transition(.move(edge: .top).combined(with: .opacity))
      }
    }
    .tint(ClinicalPalette.teal)
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

private struct NativeAlertBanner: View {
  let alert: NativeScheduleAlert
  let unreadCount: Int
  let action: () -> Void

  var body: some View {
    Button(action: action) {
      HStack(alignment: .top, spacing: 10) {
        ZStack(alignment: .topTrailing) {
          Image(systemName: "bell.badge")
            .font(.title3.weight(.bold))
            .foregroundStyle(ClinicalPalette.teal)
            .frame(width: 34, height: 34)
            .background(ClinicalPalette.tealSoft.opacity(0.9), in: RoundedRectangle(cornerRadius: 12, style: .continuous))

          Text("\(unreadCount)")
            .font(.system(size: 10, weight: .black))
            .foregroundStyle(.white)
            .padding(.horizontal, 5)
            .padding(.vertical, 2)
            .background(ClinicalPalette.teal, in: Capsule())
            .offset(x: 6, y: -5)
        }

        VStack(alignment: .leading, spacing: 2) {
          Text(alert.title)
            .font(.subheadline.weight(.bold))
            .foregroundStyle(ClinicalPalette.ink)
            .lineLimit(1)
          Text(alert.body)
            .font(.caption.weight(.medium))
            .foregroundStyle(ClinicalPalette.muted)
            .lineLimit(2)
          if !alert.displayTime.isEmpty {
            Text(alert.displayTime)
              .font(.caption2.weight(.semibold))
              .foregroundStyle(ClinicalPalette.teal)
          }
        }

        Spacer(minLength: 4)

        Image(systemName: "chevron.right")
          .font(.caption.weight(.bold))
          .foregroundStyle(ClinicalPalette.teal)
          .padding(.top, 8)
      }
      .padding(.horizontal, 12)
      .padding(.vertical, 10)
      .frame(maxWidth: .infinity, alignment: .leading)
      .liquidGlassCard(cornerRadius: 18, tint: ClinicalPalette.tealSoft)
    }
    .buttonStyle(.plain)
  }
}

private struct NativeAlertInbox: View {
  let alerts: [NativeScheduleAlert]
  let markRead: () -> Void
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    NavigationView {
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
  case patients = "Patients"

  var id: String { rawValue }

  var systemImage: String {
    switch self {
    case .schedule:
      return "calendar"
    case .timeOff:
      return "person.crop.circle.badge.minus"
    case .patients:
      return "person.text.rectangle"
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

      Divider()

      Button(role: .destructive) {
        store.logout()
      } label: {
        Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
      }
    } label: {
      HStack(spacing: 4) {
        Text(selectedSection.rawValue)
          .font(.headline.weight(.semibold))
        Image(systemName: "chevron.down")
          .font(.caption2.weight(.bold))
      }
      .foregroundStyle(.primary)
    }
  }
}
