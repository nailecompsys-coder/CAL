import SwiftUI

struct TimeOffHomeView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection
  @State private var showingRequestSheet = false
  @State private var showingMonthMenu = false
  @State private var selectedRequest: TimeOffRequest?
  @State private var editingRequest: TimeOffRequest?
  @State private var cancelTarget: TimeOffRequest?
  @State private var actionMessage: String?
  @State private var selectedMonth = Calendar.current.dateInterval(of: .month, for: Date())?.start ?? Date()

  private var months: [Date] {
    let calendar = Calendar.current
    let firstMonth = calendar.dateInterval(of: .month, for: Date())?.start ?? Date()
    return (-1..<12).compactMap { calendar.date(byAdding: .month, value: $0, to: firstMonth) }
  }

  private var monthRequests: [TimeOffRequest] {
    let calendar = Calendar.current
    guard let interval = calendar.dateInterval(of: .month, for: selectedMonth) else { return [] }
    let monthStart = NativeDayResponse.dateFormatter.string(from: interval.start)
    let lastDay = calendar.date(byAdding: .day, value: -1, to: interval.end) ?? interval.start
    let monthEnd = NativeDayResponse.dateFormatter.string(from: lastDay)

    return store.timeOffRequests
      .filter { request in
        // Overlaps selected month: start <= monthEnd && end >= monthStart
        request.startDate <= monthEnd && request.endDate >= monthStart
      }
      .sorted { lhs, rhs in
        if lhs.startDate != rhs.startDate { return lhs.startDate < rhs.startDate }
        return lhs.id < rhs.id
      }
  }

  private var monthLabel: String {
    selectedMonth.formatted(.dateTime.month(.abbreviated).year())
  }

  private var ganttMonthDays: [ScheduleDay] {
    let calendar = Calendar.current
    guard let interval = calendar.dateInterval(of: .month, for: selectedMonth) else { return [] }
    var result: [ScheduleDay] = []
    var cursor = interval.start
    while cursor < interval.end {
      result.append(store.day(for: cursor) ?? ScheduleDay.empty(for: cursor))
      guard let next = calendar.date(byAdding: .day, value: 1, to: cursor) else { break }
      cursor = next
    }
    return result
  }

  private var ganttModel: TimeOffGanttModel {
    TimeOffGanttModel.build(month: selectedMonth, days: ganttMonthDays, surgeons: store.surgeons)
  }

  var body: some View {
    CalNavigation {
      ZStack {
        ScheduleWaterBackground()

        ScrollView {
          VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
              Button {
                showingRequestSheet = true
              } label: {
                Label("Request Time Off", systemImage: "plus.circle.fill")
                  .font(.subheadline.weight(.semibold))
                  .frame(maxWidth: .infinity)
                  .padding(.vertical, 10)
              }
              .buttonStyle(.borderedProminent)
              .tint(ClinicalPalette.teal)
            }

            VStack(alignment: .leading, spacing: 8) {
              Text("WHO'S OUT")
                .font(.caption.weight(.black))
                .foregroundStyle(.secondary)

              ScheduleDateStepper(
                title: selectedMonth.formatted(.dateTime.month(.wide).year()),
                subtitle: "Practice coverage",
                previousAction: { shiftMonth(-1) },
                nextAction: { shiftMonth(1) },
                onTitleTap: { showingMonthMenu = true }
              )

              TimeOffGanttView(model: ganttModel, selectedMonth: selectedMonth)

              VStack(alignment: .leading, spacing: 6) {
                Text("MY REQUESTS · \(monthLabel.uppercased())")
                  .font(.caption.weight(.black))
                  .foregroundStyle(.secondary)

                if monthRequests.isEmpty {
                  Text(store.sessionToken == nil ? "Sign in to see requests." : "No requests in \(monthLabel).")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 4)
                } else {
                  ForEach(monthRequests) { request in
                    Button {
                      selectedRequest = request
                    } label: {
                      TimeOffRequestRow(request: request)
                    }
                    .buttonStyle(.plain)
                    .disabled(!request.canManage)
                  }
                }
              }
              .padding(.top, 4)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.tealSoft)
            .confirmationDialog("Select month", isPresented: $showingMonthMenu, titleVisibility: .visible) {
              ForEach(months, id: \.self) { month in
                Button(month.formatted(.dateTime.month(.wide).year())) {
                  selectedMonth = month
                }
              }
              Button("Cancel", role: .cancel) {}
            }
          }
          .padding(.horizontal, 16)
          .padding(.top, 8)
          .padding(.bottom, 18)
          .calReadableColumn(ClinicalLayout.wideColumn)
        }
      }
      .navigationTitle("Time Off")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .principal) {
          CALNativeTitleMenu(selectedSection: $selectedSection, store: store)
        }

        ToolbarItemGroup(placement: .navigationBarTrailing) {
          NativeAlertsToolbarButton(store: store)
          Button {
            showingRequestSheet = true
          } label: {
            Image(systemName: "plus")
          }
        }
      }
      .sheet(isPresented: $showingRequestSheet) {
        TimeOffRequestForm(store: store, defaultDate: selectedMonth)
      }
      .sheet(item: $editingRequest) { request in
        TimeOffRequestForm(store: store, existing: request)
      }
      .confirmationDialog(
        selectedRequest.map { "\($0.dateRange) · \($0.reason.isEmpty ? "Time off" : $0.reason)" } ?? "Time Off",
        isPresented: Binding(
          get: { selectedRequest != nil },
          set: { if !$0 { selectedRequest = nil } }
        ),
        titleVisibility: .visible
      ) {
        Button("Modify") {
          editingRequest = selectedRequest
        }
        Button("Cancel Time Off", role: .destructive) {
          cancelTarget = selectedRequest
        }
        Button("Close", role: .cancel) {}
      } message: {
        if let selectedRequest {
          Text(selectedRequest.status.lowercased() == "approved"
            ? "Approved time off can be canceled, or changed and sent back for approval."
            : "This request is pending. You can change it or cancel it.")
        }
      }
      .alert(
        "Cancel this time off?",
        isPresented: Binding(
          get: { cancelTarget != nil },
          set: { if !$0 { cancelTarget = nil } }
        )
      ) {
        Button("Keep", role: .cancel) {}
        Button("Cancel Time Off", role: .destructive) {
          if let cancelTarget {
            Task {
              await cancelRequest(cancelTarget)
            }
          }
        }
      } message: {
        Text("This removes it from your schedule.")
      }
      .alert("Time Off", isPresented: Binding(
        get: { actionMessage != nil },
        set: { if !$0 { actionMessage = nil } }
      )) {
        Button("OK", role: .cancel) {}
      } message: {
        if let actionMessage {
          Text(actionMessage)
        }
      }
      .task {
        let firstMonth = Calendar.current.dateInterval(of: .month, for: Date())?.start ?? Date()
        await store.loadLookahead(containing: firstMonth, daysAhead: 365)
      }
      .onChange(of: selectedMonth) { _ in
        Task {
          await store.loadLookahead(containing: selectedMonth, daysAhead: 62)
        }
      }
    }
  }

  private func cancelRequest(_ request: TimeOffRequest) async {
    do {
      try await store.cancelTimeOffRequest(id: request.id, containing: selectedMonth)
    } catch {
      actionMessage = error.localizedDescription
    }
  }

  private func shiftMonth(_ delta: Int) {
    let calendar = Calendar.current
    guard let next = calendar.date(byAdding: .month, value: delta, to: selectedMonth) else { return }
    selectedMonth = calendar.dateInterval(of: .month, for: next)?.start ?? next
  }
}

private struct TimeOffRequestRow: View {
  let request: TimeOffRequest

  var body: some View {
    HStack(spacing: 8) {
      StatusDot(status: request.status)

      Text(request.dateRange)
        .font(ClinicalTypography.caption)
        .foregroundStyle(ClinicalPalette.ink)
        .lineLimit(1)
        .minimumScaleFactor(0.8)
        .fixedSize(horizontal: true, vertical: false)
        .layoutPriority(1)

      Text(request.reason.isEmpty ? "Time off" : request.reason)
        .font(.caption)
        .foregroundStyle(.secondary)
        .lineLimit(1)
        .minimumScaleFactor(0.85)

      Spacer(minLength: 4)

      Text(request.status.capitalized)
        .font(ClinicalTypography.badge)
        .foregroundStyle(statusColor(request.status))
        .fixedSize(horizontal: true, vertical: false)

      if request.canManage {
        Image(systemName: "chevron.right")
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)
      }
    }
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
      .frame(width: 8, height: 8)
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

