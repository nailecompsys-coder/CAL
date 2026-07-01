import SwiftUI

struct CALNativeTabShell: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var selectedSection: CALNativeSection = .schedule

  var body: some View {
    Group {
      switch selectedSection {
      case .schedule:
        ScheduleHomeView(store: store, selectedSection: $selectedSection)
      case .timeOff:
        TimeOffHomeView(store: store, selectedSection: $selectedSection)
      case .patients:
        PatientScheduleView(store: store, selectedSection: $selectedSection)
      }
    }
    .tint(ClinicalPalette.teal)
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
