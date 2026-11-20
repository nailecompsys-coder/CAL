import SwiftUI

struct TimeOffRequestForm: View {
  @ObservedObject var store: NativeScheduleStore
  var existing: TimeOffRequest? = nil
  @Environment(\.dismiss) private var dismiss

  @State private var startDate = Date()
  @State private var endDate = Date()
  @State private var segments: [RequestSegment] = []
  @State private var reason = "Day Off"
  @State private var notes = ""
  @State private var message: String?
  @State private var isSubmitting = false
  @State private var receipt: TimeOffReceipt?
  @State private var editingDate: RequestDateField?
  @State private var capacity: TimeOffCapacityPreview?

  private let reasons = ["Day Off", "No Call", "Vacation", "CME", "Partial Day", "Medical"]
  private var isEditing: Bool { existing != nil }

  init(store: NativeScheduleStore, existing: TimeOffRequest? = nil, defaultDate: Date = Date()) {
    self.store = store
    self.existing = existing
    if let existing {
      let knownReasons = ["Day Off", "No Call", "Vacation", "CME", "Partial Day", "Medical"]
      _startDate = State(initialValue: existing.parsedStartDate ?? Date())
      _endDate = State(initialValue: existing.parsedEndDate ?? Date())
      _reason = State(initialValue: knownReasons.contains(existing.reason) ? existing.reason : (existing.reason.isEmpty ? "Day Off" : existing.reason))
      _notes = State(initialValue: existing.notes)
      _segments = State(initialValue: existing.requestSegments)
    } else {
      let seed = Self.clampedRequestDate(defaultDate)
      _startDate = State(initialValue: seed)
      _endDate = State(initialValue: seed)
    }
  }

  private static func clampedRequestDate(_ date: Date) -> Date {
    let calendar = Calendar.current
    let monthStart = calendar.dateInterval(of: .month, for: date)?.start ?? calendar.startOfDay(for: date)
    let today = calendar.startOfDay(for: Date())
    return monthStart < today ? today : monthStart
  }

  var body: some View {
    CalNavigation {
      ZStack {
        ScheduleWaterBackground()

        ScrollView {
          if let receipt {
            confirmationContent(receipt)
          } else {
            requestFormContent
          }
        }
      }
      .navigationTitle(receipt == nil ? (isEditing ? "Modify Time Off" : "Request Time Off") : (receipt?.isApproved == true ? "Time Off Approved" : (isEditing ? "Request Updated" : "Request Sent")))
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          if receipt == nil {
            Button("Cancel") {
              dismiss()
            }
          }
        }

        ToolbarItem(placement: .confirmationAction) {
          if receipt != nil {
            Button("OK") {
              dismiss()
            }
            .font(.body.weight(.semibold))
          } else {
            Button(isSubmitting ? "Saving" : (capacity?.isRed == true ? "Send" : (isEditing ? "Save" : "Submit"))) {
              Task {
                await submit()
              }
            }
            // Never blocked: on red the surgeon has already seen who is off.
            .disabled(isSubmitting || store.sessionToken == nil)
          }
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

  private var requestFormContent: some View {
    VStack(alignment: .leading, spacing: 8) {
      DashboardSection(title: "Range") {
        RequestDateButton(title: "Start", date: startDate) {
          editingDate = .start
        }

        Divider().opacity(0.45)

        RequestDateButton(title: "End", date: endDate) {
          editingDate = .end
        }

        if existing?.status.lowercased() == "approved" {
          Text("Changing this sends it back for approval.")
            .font(.caption)
            .foregroundStyle(ClinicalPalette.warningText)
        }

        if let capacity, capacity.isRed || capacity.isYellow {
          TimeOffCapacityChip(
            capacity: capacity,
            isSubmitting: isSubmitting,
            changeDates: { editingDate = .start },
            send: { Task { await submit() } }
          )
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

      .task(id: capacityKey) {
        // Wait for the picker to settle, then ask the server who else is off.
        try? await Task.sleep(nanoseconds: 400_000_000)
        guard !Task.isCancelled else { return }
        let preview = await store.previewTimeOffRequest(
          excludeRequestId: existing?.id,
          startDate: startDate,
          endDate: endDate,
          reason: reason,
          segments: segments
        )
        guard !Task.isCancelled else { return }
        capacity = preview
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

  private func confirmationContent(_ receipt: TimeOffReceipt) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      DashboardSection(title: "Sent") {
        confirmationRow(title: "Dates", value: receipt.rangeLabel)
        Divider().opacity(0.45)
        confirmationRow(title: "Type", value: receipt.reason)
        if !receipt.notes.isEmpty {
          Divider().opacity(0.45)
          confirmationRow(title: "Note", value: receipt.notes)
        }
        Divider().opacity(0.45)
        confirmationRow(title: "Status", value: receipt.isApproved ? "Approved" : "Pending approval")
      }

      DashboardSection(title: "Days") {
        ForEach(receipt.segments) { segment in
          HStack {
            Text(segment.date.formatted(.dateTime.month(.twoDigits).day(.twoDigits)))
              .font(.subheadline.weight(.semibold))
              .foregroundStyle(ClinicalPalette.ink)
            Spacer()
            Text(segment.summary)
              .font(.caption2.weight(.semibold))
              .foregroundStyle(.secondary)
          }
          .padding(.vertical, 2)
        }
      }

      if let warning = primaryWarning(from: receipt.warnings) {
        DashboardSection(title: "Review note") {
          Text(cleanWarning(warning))
            .font(.caption)
            .foregroundStyle(ClinicalPalette.warningText)
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 12, tint: ClinicalPalette.amber)
        }
      }

      Button {
        dismiss()
      } label: {
        Text("OK")
          .font(.headline.weight(.semibold))
          .foregroundStyle(.white)
          .frame(maxWidth: .infinity)
          .padding(.vertical, 14)
          .background(ClinicalPalette.teal, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
      }
      .buttonStyle(.plain)
      .padding(.top, 8)
    }
    .padding(.horizontal, 16)
    .padding(.top, 8)
    .padding(.bottom, 18)
  }

  private func confirmationRow(title: String, value: String) -> some View {
    HStack(alignment: .top, spacing: 10) {
      Text(title)
        .font(.subheadline.weight(.semibold))
        .foregroundStyle(ClinicalPalette.ink)
      Spacer()
      Text(value)
        .font(.subheadline.weight(.semibold))
        .foregroundStyle(ClinicalPalette.teal)
        .multilineTextAlignment(.trailing)
    }
    .padding(.vertical, 4)
  }

  /// Changes whenever the dates, half-days or type change, so the preview reruns.
  private var capacityKey: String {
    let days = segments.map { "\(dateKey($0.date)):\($0.isFullDay ? "full" : "\($0.start)-\($0.end)")" }
    return ([reason] + days).joined(separator: "|")
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
      let result: TimeOffSubmitResult
      if let existing {
        result = try await store.updateTimeOffRequest(
          id: existing.id,
          startDate: startDate,
          endDate: endDate,
          reason: reason,
          notes: notes,
          segments: segments
        )
      } else {
        result = try await store.submitTimeOffRequest(
          startDate: startDate,
          endDate: endDate,
          reason: reason,
          notes: notes,
          segments: segments
        )
      }
      isSubmitting = false
      receipt = TimeOffReceipt(
        startDate: startDate,
        endDate: endDate,
        reason: reason,
        notes: notes.trimmingCharacters(in: .whitespacesAndNewlines),
        segments: segments,
        warnings: result.warnings,
        isApproved: result.isApproved
      )
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

  private func primaryWarning(from warnings: [String]) -> String? {
    warnings.first { warning in
      warning.localizedCaseInsensitiveContains("already has")
        && warning.localizedCaseInsensitiveContains("approved off")
    } ?? warnings.first
  }

  private func cleanWarning(_ warning: String) -> String {
    var cleaned = warning
      .replacingOccurrences(of: "Heads up: ", with: "")
      .replacingOccurrences(of: "Submitted. ", with: "")
      .trimmingCharacters(in: .whitespacesAndNewlines)
    if !cleaned.hasSuffix(".") {
      cleaned += "."
    }
    return cleaned
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

private struct TimeOffReceipt {
  let startDate: Date
  let endDate: Date
  let reason: String
  let notes: String
  let segments: [RequestSegment]
  let warnings: [String]
  var isApproved: Bool = false

  var rangeLabel: String {
    let start = startDate.formatted(.dateTime.month(.abbreviated).day().year())
    if Calendar.current.isDate(startDate, inSameDayAs: endDate) {
      return start
    }
    let end = endDate.formatted(.dateTime.month(.abbreviated).day().year())
    return "\(start) – \(end)"
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
    CalNavigation {
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


/// Chris's rule: two off in a group is yellow, a third is red. Shows who is
/// already off (approved or pending). Red offers Change dates or Send to Shannon.
private struct TimeOffCapacityChip: View {
  let capacity: TimeOffCapacityPreview
  let isSubmitting: Bool
  let changeDates: () -> Void
  let send: () -> Void

  private var tint: Color { capacity.isRed ? Color.red : ClinicalPalette.warningText }

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Label(capacity.isRed ? "Red alert" : "Heads up", systemImage: capacity.isRed ? "exclamationmark.octagon.fill" : "exclamationmark.triangle.fill")
        .font(.subheadline.weight(.bold))
        .foregroundStyle(tint)

      // Day by day, so Dec 3 can be yellow while Dec 4-5 are red.
      ForEach(capacity.days) { day in
        HStack(spacing: 6) {
          Circle()
            .fill(day.isRed ? Color.red : ClinicalPalette.warningText)
            .frame(width: 8, height: 8)
          Text(day.label)
            .font(.caption.weight(.semibold))
            .foregroundStyle(ClinicalPalette.ink)
          Text(day.booked.isEmpty ? "· \(day.offCount) off" : "· \(day.booked)")
            .font(.caption)
            .foregroundStyle(.secondary)
          Spacer(minLength: 4)
          Text(day.isRed ? "Red" : "Yellow")
            .font(.caption2.weight(.bold))
            .foregroundStyle(day.isRed ? Color.red : ClinicalPalette.warningText)
        }
        .accessibilityElement(children: .combine)
      }

      if !capacity.offList.isEmpty {
        Text("Already off:")
          .font(.caption.weight(.semibold))
          .foregroundStyle(ClinicalPalette.ink)
          .padding(.top, 2)
      }

      ForEach(capacity.offList) { person in
        HStack(spacing: 8) {
          Text(person.initials)
            .font(.caption2.weight(.black))
            .frame(width: 28, height: 28)
            .background(ClinicalPalette.porcelainChip, in: Circle())
          VStack(alignment: .leading, spacing: 1) {
            Text(person.name.isEmpty ? person.initials : person.name)
              .font(.caption.weight(.semibold))
              .foregroundStyle(ClinicalPalette.ink)
            Text(person.when)
              .font(.caption2)
              .foregroundStyle(.secondary)
          }
          Spacer(minLength: 4)
          Text(person.isApproved ? "Approved" : "Pending")
            .font(.caption2.weight(.bold))
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .foregroundStyle(person.isApproved ? ClinicalPalette.teal : ClinicalPalette.warningText)
            .background((person.isApproved ? ClinicalPalette.teal : ClinicalPalette.warningText).opacity(0.14), in: Capsule())
        }
        .accessibilityElement(children: .combine)
      }

      if capacity.isRed {
        HStack(spacing: 8) {
          Button(action: changeDates) {
            Text("Change dates")
              .font(.subheadline.weight(.semibold))
              .frame(maxWidth: .infinity)
              .padding(.vertical, 9)
              .background(ClinicalPalette.card, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
          }
          .buttonStyle(.plain)

          Button(action: send) {
            Text(isSubmitting ? "Sending" : "Send to Shannon")
              .font(.subheadline.weight(.semibold))
              .foregroundStyle(.white)
              .frame(maxWidth: .infinity)
              .padding(.vertical, 9)
              .background(Color.red, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
          }
          .buttonStyle(.plain)
          .disabled(isSubmitting)
        }
        Text("Send saves your request and gives Shannon a red alert to work out.")
          .font(.caption2)
          .foregroundStyle(.secondary)
      }
    }
    .padding(10)
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(
      (capacity.isRed ? Color.red : ClinicalPalette.amber).opacity(0.10),
      in: RoundedRectangle(cornerRadius: 12, style: .continuous)
    )
    .overlay(
      RoundedRectangle(cornerRadius: 12, style: .continuous)
        .stroke((capacity.isRed ? Color.red : ClinicalPalette.warningText).opacity(0.45), lineWidth: 1)
    )
  }
}
