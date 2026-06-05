import SwiftUI

struct TimeOffHomeView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection
  @State private var showingRequestSheet = false
  @State private var selectedMonth = Calendar.current.dateInterval(of: .month, for: Date())?.start ?? Date()

  private var months: [Date] {
    let calendar = Calendar.current
    let firstMonth = calendar.dateInterval(of: .month, for: Date())?.start ?? Date()
    return (0..<12).compactMap { calendar.date(byAdding: .month, value: $0, to: firstMonth) }
  }

  private var selectedMonthDays: [ScheduleDay] {
    let calendar = Calendar.current
    return store.days
      .filter { calendar.isDate($0.date, equalTo: selectedMonth, toGranularity: .month) }
      .sorted { $0.date < $1.date }
  }

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        ScrollView {
          VStack(alignment: .leading, spacing: 8) {
            Button {
              showingRequestSheet = true
            } label: {
              HStack(spacing: 10) {
                Image(systemName: "plus.circle.fill")
                  .font(.body)
                  .foregroundStyle(ClinicalPalette.teal)

                VStack(alignment: .leading, spacing: 2) {
                  Text("Request Time Off")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                  Text("Pick a range, then set full or half days.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }

                Spacer()

                Image(systemName: "chevron.right")
                  .font(.caption2.weight(.semibold))
                  .foregroundStyle(.tertiary)
              }
              .padding(.horizontal, 12)
              .padding(.vertical, 10)
              .frame(maxWidth: .infinity, alignment: .leading)
              .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.cardStrong)
            }
            .buttonStyle(.plain)

            DashboardSection(title: "Requests") {
              if store.timeOffRequests.isEmpty {
                Text(store.sessionToken == nil ? "Sign in to see requests." : "No requests in this range.")
                  .font(.caption)
                  .foregroundStyle(.secondary)
              } else {
                ForEach(store.timeOffRequests) { request in
                  TimeOffRequestRow(request: request)
                }
              }
            }

            TimeOffInfoBanner()

            MonthPillPicker(months: months, selectedMonth: $selectedMonth)

            DashboardSection(title: selectedMonth.formatted(.dateTime.month(.wide).year())) {
              MonthTimeOffList(days: selectedMonthDays)
            }
          }
          .padding(.horizontal, 16)
          .padding(.top, 8)
          .padding(.bottom, 18)
        }
      }
      .navigationTitle("Time Off")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .principal) {
          CALNativeTitleMenu(selectedSection: $selectedSection, store: store)
        }

        ToolbarItem(placement: .navigationBarTrailing) {
          Button {
            showingRequestSheet = true
          } label: {
            Image(systemName: "plus")
          }
        }
      }
      .sheet(isPresented: $showingRequestSheet) {
        TimeOffRequestForm(store: store)
      }
      .task {
        let firstMonth = Calendar.current.dateInterval(of: .month, for: Date())?.start ?? Date()
        await store.loadLookahead(containing: firstMonth, daysAhead: 365)
      }
    }
  }
}

private struct TimeOffRequestRow: View {
  let request: TimeOffRequest

  var body: some View {
    HStack(spacing: 10) {
      StatusDot(status: request.status)

      VStack(alignment: .leading, spacing: 3) {
        Text("\(request.surgeonInitials) \(request.dateRange)")
          .font(.subheadline.weight(.semibold))
        Text(request.reason.isEmpty ? "Time off" : request.reason)
          .font(.caption2)
          .foregroundStyle(.secondary)
      }

      Spacer()

      Text(request.status.capitalized)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(statusColor(request.status))
    }
    .padding(.vertical, 1)
  }

  private func statusColor(_ status: String) -> Color {
    switch status.lowercased() {
    case "approved":
      return ClinicalPalette.teal
    case "denied":
      return .red
    default:
      return .orange
    }
  }
}

private struct StatusDot: View {
  let status: String

  var body: some View {
    Circle()
      .fill(color)
      .frame(width: 10, height: 10)
  }

  private var color: Color {
    switch status.lowercased() {
    case "approved":
      return ClinicalPalette.teal
    case "denied":
      return .red
    default:
      return .orange
    }
  }
}
