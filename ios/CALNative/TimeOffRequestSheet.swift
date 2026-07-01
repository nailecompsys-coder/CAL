import SwiftUI

struct TimeOffRequestForm: View {
  @ObservedObject var store: NativeScheduleStore
  @Environment(\.dismiss) private var dismiss

  @State private var startDate = Date()
  @State private var endDate = Date()
  @State private var segments: [RequestSegment] = []
  @State private var reason = "Day Off"
  @State private var notes = ""
  @State private var message: String?
  @State private var isSubmitting = false
  @State private var editingDate: RequestDateField?

  private let reasons = ["Day Off", "No Call", "Vacation", "CME", "Partial Day", "Medical"]

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        ScrollView {
          VStack(alignment: .leading, spacing: 8) {
            DashboardSection(title: "Range") {
              RequestDateButton(title: "Start", date: startDate) {
                editingDate = .start
              }

              Divider().opacity(0.45)

              RequestDateButton(title: "End", date: endDate) {
                editingDate = .end
              }

              if let message {
                Text(message)
                  .font(.caption)
                  .foregroundStyle(.secondary)
                  .padding(.horizontal, 10)
                  .padding(.vertical, 8)
                  .frame(maxWidth: .infinity, alignment: .leading)
                  .liquidGlassCard(cornerRadius: 12, tint: ClinicalPalette.amber)
              }

              Text(rangeSummary)
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
            .sheet(item: $editingDate) { field in
              RequestDatePickerSheet(title: field.title, date: dateBinding(for: field))
            }
            .onChange(of: startDate) { newValue in
              if endDate < newValue {
                endDate = newValue
              }
              normalizeSegments()
            }
            .onChange(of: endDate) { newValue in
              if newValue < startDate {
                startDate = newValue
              }
              normalizeSegments()
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

  private var rangeSummary: String {
    let count = segments.count
    if count == 1 {
      return "1 day selected."
    }
    return "\(count) days selected."
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

  private func dateBinding(for field: RequestDateField) -> Binding<Date> {
    Binding(
      get: {
        switch field {
        case .start:
          return startDate
        case .end:
          return endDate
        }
      },
      set: { newValue in
        switch field {
        case .start:
          startDate = Calendar.current.startOfDay(for: newValue)
          if endDate < startDate {
            endDate = startDate
          }
        case .end:
          endDate = Calendar.current.startOfDay(for: newValue)
          if endDate < startDate {
            startDate = endDate
          }
        }
        normalizeSegments()
      }
    )
  }
}

private enum RequestDateField: String, Identifiable {
  case start
  case end

  var id: String { rawValue }

  var title: String {
    switch self {
    case .start:
      return "Start Date"
    case .end:
      return "End Date"
    }
  }
}

private struct RequestDateButton: View {
  let title: String
  let date: Date
  let action: () -> Void

  var body: some View {
    Button(action: action) {
      HStack(spacing: 10) {
        Text(title)
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(.primary)

        Spacer()

        Text(date.formatted(.dateTime.month(.abbreviated).day().year()))
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(ClinicalPalette.teal)

        Image(systemName: "calendar")
          .font(.caption.weight(.semibold))
          .foregroundStyle(ClinicalPalette.teal)
      }
      .padding(.vertical, 4)
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .accessibilityLabel("\(title), \(date.formatted(.dateTime.month(.wide).day().year()))")
  }
}

private struct RequestDatePickerSheet: View {
  let title: String
  @Binding var date: Date
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    NavigationView {
      DatePicker(title, selection: $date, displayedComponents: .date)
        .datePickerStyle(.graphical)
        .padding()
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
          ToolbarItem(placement: .confirmationAction) {
            Button("Done") {
              dismiss()
            }
          }
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
