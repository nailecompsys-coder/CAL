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

private struct TimeOffRequestForm: View {
  @ObservedObject var store: NativeScheduleStore
  @Environment(\.dismiss) private var dismiss

  @State private var startDate = Date()
  @State private var endDate = Date()
  @State private var segments: [RequestSegment] = []
  @State private var reason = "Day Off"
  @State private var notes = ""
  @State private var message: String?
  @State private var isSubmitting = false

  private let reasons = ["Day Off", "No Call", "Vacation", "CME", "Partial Day", "Medical"]

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        ScrollView {
          VStack(alignment: .leading, spacing: 8) {
            DashboardSection(title: "Range") {
              CompactDatePickerRow(title: "Start", date: $startDate)
                .onChange(of: startDate) { newValue in
                  if endDate < newValue {
                    endDate = newValue
                  }
                  normalizeSegments()
                }

              Divider().opacity(0.45)

              CompactDatePickerRow(title: "End", date: $endDate)
                .onChange(of: endDate) { newValue in
                  if newValue < startDate {
                    startDate = newValue
                  }
                  normalizeSegments()
                }

              Text(rangeSummary)
                .font(.caption2)
                .foregroundStyle(.secondary)
            }

            DashboardSection(title: "Days") {
              ForEach(segments) { segment in
                RequestSegmentRow(segment: segment) { preset in
                  setSegment(segment.date, preset: preset)
                }
              }
            }

            DashboardSection(title: "Details") {
              Picker("Type", selection: $reason) {
                ForEach(reasons, id: \.self) { item in
                  Text(item).tag(item)
                }
              }
              .font(.subheadline)

              TextEditor(text: $notes)
                .frame(minHeight: 76)
                .font(.subheadline)
                .scrollContentBackgroundHiddenIfAvailable()
                .overlay(alignment: .topLeading) {
                  if notes.isEmpty {
                    Text("Optional note")
                      .font(.subheadline)
                      .foregroundStyle(.secondary)
                      .padding(.top, 8)
                      .padding(.leading, 5)
                  }
                }
            }

            if let message {
              Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
            }
          }
          .padding(.horizontal, 16)
          .padding(.top, 8)
          .padding(.bottom, 18)
        }
      }
      .navigationTitle("Request Time Off")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") {
            dismiss()
          }
        }

        ToolbarItem(placement: .confirmationAction) {
          Button(isSubmitting ? "Submitting" : "Submit") {
            Task {
              await submit()
            }
          }
          .disabled(isSubmitting || store.sessionToken == nil)
        }
      }
      .onAppear {
        normalizeSegments()
        if store.sessionToken == nil {
          message = "Sign in is needed before native requests can be submitted."
        }
      }
    }
  }

  private func submit() async {
    isSubmitting = true
    message = nil

    do {
      try await store.submitTimeOffRequest(
        startDate: startDate,
        endDate: endDate,
        reason: reason,
        notes: notes,
        segments: segments
      )
      isSubmitting = false
      dismiss()
    } catch {
      isSubmitting = false
      message = error.localizedDescription
    }
  }

  private var rangeSummary: String {
    let count = segments.count
    if count == 1 {
      return "1 day selected."
    }
    return "\(count) days selected."
  }

  private func normalizeSegments() {
    let existing = Dictionary(uniqueKeysWithValues: segments.map { ($0.id, $0) })
    segments = datesBetween(startDate, endDate).map { date in
      existing[dateKey(date)] ?? RequestSegment(date: date, isFullDay: true, start: "07:00", end: "17:00")
    }
  }

  private func setSegment(_ date: Date, preset: RequestSegmentPreset) {
    segments = segments.map { segment in
      guard Calendar.current.isDate(segment.date, inSameDayAs: date) else {
        return segment
      }

      switch preset {
      case .full:
        return RequestSegment(date: segment.date, isFullDay: true, start: "07:00", end: "17:00")
      case .am:
        return RequestSegment(date: segment.date, isFullDay: false, start: "07:00", end: "12:00")
      case .pm:
        return RequestSegment(date: segment.date, isFullDay: false, start: "12:00", end: "17:00")
      }
    }
  }

  private func datesBetween(_ start: Date, _ end: Date) -> [Date] {
    let calendar = Calendar.current
    var dates: [Date] = []
    var current = calendar.startOfDay(for: start)
    let last = calendar.startOfDay(for: end)

    while current <= last {
      dates.append(current)
      current = calendar.date(byAdding: .day, value: 1, to: current) ?? last.addingTimeInterval(86_400)
    }

    return dates
  }
}

private struct TimeOffInfoBanner: View {
  var body: some View {
    Label {
      Text("Pick a month to scan requested and approved time off before choosing your dates.")
        .font(.caption)
        .foregroundStyle(ClinicalPalette.muted)
        .fixedSize(horizontal: false, vertical: true)
    } icon: {
      Image(systemName: "info.circle.fill")
        .foregroundStyle(ClinicalPalette.teal)
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 9)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.tealSoft)
  }
}

private struct MonthPillPicker: View {
  let months: [Date]
  @Binding var selectedMonth: Date
  private let columns = Array(repeating: GridItem(.flexible(), spacing: 7), count: 4)

  var body: some View {
    LazyVGrid(columns: columns, spacing: 7) {
        ForEach(months, id: \.self) { month in
          Button {
            selectedMonth = month
          } label: {
            Text(month.formatted(.dateTime.month(.abbreviated)))
              .font(.caption.weight(.semibold))
              .lineLimit(1)
              .minimumScaleFactor(0.85)
              .foregroundStyle(isSelected(month) ? .white : ClinicalPalette.teal)
              .frame(maxWidth: .infinity)
              .padding(.vertical, 7)
              .background(isSelected(month) ? ClinicalPalette.teal : ClinicalPalette.cardStrong, in: Capsule())
              .overlay {
                Capsule()
                  .stroke(ClinicalPalette.teal.opacity(isSelected(month) ? 0 : 0.24), lineWidth: 0.8)
              }
          }
          .buttonStyle(.plain)
        }
    }
    .padding(.vertical, 2)
  }

  private func isSelected(_ month: Date) -> Bool {
    Calendar.current.isDate(month, equalTo: selectedMonth, toGranularity: .month)
  }
}

private struct MonthTimeOffList: View {
  let days: [ScheduleDay]

  private var visibleDays: [ScheduleDay] {
    days.filter { !$0.requestedOff.isEmpty || !$0.off.isEmpty }
  }

  var body: some View {
    if visibleDays.isEmpty {
      EmptyDashboardRow(title: "No requested or approved time off.")
    } else {
      VStack(alignment: .leading, spacing: 7) {
        ForEach(visibleDays) { day in
          MonthTimeOffDayRow(day: day)
        }
      }
    }
  }
}

private struct MonthTimeOffDayRow: View {
  let day: ScheduleDay

  var body: some View {
    VStack(alignment: .leading, spacing: 5) {
      Text(day.date.formatted(.dateTime.weekday(.abbreviated).month(.defaultDigits).day()))
        .font(.caption.weight(.semibold))
        .foregroundStyle(ClinicalPalette.ink)

      if !day.requestedOff.isEmpty {
        TimeOffStatusLine(label: "Requested", initials: day.requestedOff, tint: ClinicalPalette.amber, textColor: .orange)
      }

      if !day.off.isEmpty {
        TimeOffStatusLine(label: "Approved", initials: day.off, tint: ClinicalPalette.mint, textColor: ClinicalPalette.scrubInk)
      }
    }
    .padding(.vertical, 2)
  }
}

private struct TimeOffStatusLine: View {
  let label: String
  let initials: [String]
  let tint: Color
  let textColor: Color

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 7) {
      Text(label)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(ClinicalPalette.muted)
        .frame(width: 58, alignment: .leading)

      TimeOffInitialsPills(items: initials, tint: tint, textColor: textColor)
    }
  }
}

private struct TimeOffInitialsPills: View {
  let items: [String]
  let tint: Color
  let textColor: Color

  var body: some View {
    HStack(spacing: 5) {
      ForEach(items, id: \.self) { item in
        Text(item)
          .font(.caption2.weight(.semibold))
          .padding(.horizontal, 8)
          .padding(.vertical, 4)
          .background(tint.opacity(0.92), in: Capsule())
          .overlay {
            Capsule()
              .stroke(textColor.opacity(0.24), lineWidth: 0.75)
          }
          .foregroundStyle(textColor)
      }
    }
  }
}

private struct RequestSegmentRow: View {
  let segment: RequestSegment
  let onChange: (RequestSegmentPreset) -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 7) {
      HStack {
        Text(segment.date.formatted(.dateTime.month(.twoDigits).day(.twoDigits)))
          .font(.subheadline.weight(.semibold))

        Spacer()

        Text(segment.summary)
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)
      }

      Picker("Day portion", selection: Binding(
        get: { segment.preset },
        set: { onChange($0) }
      )) {
        ForEach(RequestSegmentPreset.allCases) { preset in
          Text(preset.label).tag(preset)
        }
      }
      .pickerStyle(.segmented)
    }
    .padding(.vertical, 2)
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
