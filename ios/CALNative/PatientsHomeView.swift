import SwiftUI

struct PatientsHomeView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        ScrollView {
          VStack(alignment: .leading, spacing: 8) {
            DashboardSection(title: "Today") {
              if let today = store.patientToday {
                PatientSummaryRow(summary: today)
              } else {
                EmptyDashboardRow(title: "No patient assignments")
              }
            }

            DashboardSection(title: "Upcoming") {
              if store.patientUpcoming.isEmpty {
                EmptyDashboardRow(title: "No upcoming patient assignments")
              } else {
                ForEach(store.patientUpcoming) { summary in
                  PatientSummaryRow(summary: summary)
                }
              }
            }
          }
          .padding(.horizontal, 16)
          .padding(.top, 8)
          .padding(.bottom, 18)
        }
      }
      .navigationTitle("Patients")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .principal) {
          CALNativeTitleMenu(selectedSection: $selectedSection, store: store)
        }
      }
    }
  }
}

private struct PatientSummaryRow: View {
  let summary: PatientSummary

  var body: some View {
    HStack(spacing: 10) {
      Image(systemName: "person.2")
        .foregroundStyle(ClinicalPalette.teal)
        .frame(width: 22)

      VStack(alignment: .leading, spacing: 2) {
        Text("\(summary.count) patients")
          .font(.subheadline.weight(.semibold))
        Text(summary.subtitle)
          .font(.caption2)
          .foregroundStyle(.secondary)
      }

      Spacer()
    }
    .padding(.vertical, 1)
  }
}
