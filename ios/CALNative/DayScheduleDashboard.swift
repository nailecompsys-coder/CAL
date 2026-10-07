import SwiftUI

struct DayScheduleDashboard: View {
  let day: ScheduleDay
  let days: [ScheduleDay]
  let statusMessage: String?
  let isReadOnly: Bool
  let coverAction: (ScheduleAssignment) -> Void
  let onSavePersonalItem: (PersonalCalendarItem?, String, String, String?, String?, Date, Date) async throws -> Void
  let onDeletePersonalItem: (PersonalCalendarItem) async throws -> Void
  var whosWhereAction: (() -> Void)? = nil

  @State private var personalEditor: PersonalEditorTarget?
  @State private var selectedMeeting: MeetingDetail?

  private struct MeetingDetail: Identifiable {
    let date: Date
    let item: DoctorScheduleItem
    var id: String { "\(dateKey(date))-\(item.id)" }
  }

  private enum PersonalEditorTarget: Identifiable {
    case create
    case edit(PersonalCalendarItem)

    var id: String {
      switch self {
      case .create:
        return "create"
      case .edit(let item):
        return "edit-\(item.id)"
      }
    }

    var item: PersonalCalendarItem? {
      if case let .edit(item) = self { return item }
      return nil
    }
  }

  private var orderedDays: [ScheduleDay] {
    var byId = Dictionary(uniqueKeysWithValues: days.map { ($0.id, $0) })
    byId[day.id] = day
    return byId.values.sorted { $0.date < $1.date }
  }

  private var nextMeeting: MeetingDetail? {
    let calendar = Calendar.current
    let start = calendar.startOfDay(for: day.date)
    let end = calendar.date(byAdding: .day, value: 30, to: start) ?? start
    for candidate in orderedDays {
      let candidateDate = calendar.startOfDay(for: candidate.date)
      if candidateDate > start, candidateDate <= end, let item = candidate.meetings.first {
        return MeetingDetail(date: candidate.date, item: item)
      }
    }
    return nil
  }

  private var nextPersonal: (date: Date, content: String)? {
    nextAgendaItem { day in
      day.personalItems.first?.displayTitle
    }
  }

  private func nextAgendaItem(_ contentForDay: (ScheduleDay) -> String?) -> (date: Date, content: String)? {
    let calendar = Calendar.current
    let start = calendar.startOfDay(for: day.date)
    let end = calendar.date(byAdding: .day, value: 30, to: start) ?? start

    for candidate in orderedDays {
      let candidateDate = calendar.startOfDay(for: candidate.date)
      guard candidateDate > start, candidateDate <= end else {
        continue
      }

      if let content = contentForDay(candidate), !content.isEmpty {
        return (candidate.date, content)
      }
    }

    return nil
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        if let statusMessage {
          Label(statusMessage, systemImage: "exclamationmark.triangle")
            .font(.footnote)
            .foregroundStyle(.secondary)
            .calCard(padding: 12)
        }

        VStack(spacing: 10) {
          ScheduleDailyGlanceCard(day: day, coverAction: isReadOnly ? nil : coverAction)

          if let whosWhereAction {
            Button(action: whosWhereAction) {
              DayAgendaRow(
                systemImage: "square.grid.2x2.fill",
                title: "Block Schedule",
                subtitle: "Who's working where, by group"
              )
              .calCard()
            }
            .buttonStyle(.plain)
          }
        }

        DaySection(title: "Clinic & OR") {
          ClinicOrScheduleList(dayId: day.id, items: day.mySchedule)
        }

        DaySection(title: "Meetings") {
          if day.meetings.isEmpty {
            DayAgendaRow(systemImage: "person.2", title: "No meetings today", subtitle: "", isMuted: true, showsChevron: false)
          } else {
            ForEach(day.meetings) { meeting in
              meetingPreview(MeetingDetail(date: day.date, item: meeting), label: "Today")
            }
          }
          if let nextMeeting {
            Divider()
            meetingPreview(nextMeeting, label: "Next · \(nextMeeting.date.formatted(.dateTime.month(.abbreviated).day()))")
          }
        }

        DaySection(title: "Personal") {
          if day.personalItems.isEmpty {
            DayAgendaRow(systemImage: "note.text", title: "Nothing today", subtitle: "", isMuted: true, showsChevron: false)
          } else {
            ForEach(day.personalItems) { item in
              Button {
                personalEditor = .edit(item)
              } label: {
                DayAgendaRow(
                  systemImage: "note.text",
                  title: item.title,
                  subtitle: item.timeRangeLabel.isEmpty ? item.notes : item.timeRangeLabel
                )
              }
              .buttonStyle(.plain)
              .disabled(isReadOnly)
            }
          }

          if let nextPersonal {
            Divider()
            DayAgendaRow(
              systemImage: "calendar",
              title: nextPersonal.content,
              subtitle: "Next · \(nextPersonal.date.formatted(.dateTime.month(.abbreviated).day()))",
              showsChevron: false
            )
          }

          if !isReadOnly {
            Divider()
            Button {
              personalEditor = .create
            } label: {
              Label("Add Personal Item", systemImage: "plus.circle.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(ClinicalPalette.teal)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
          }
        }
      }
      .padding(.horizontal, 16)
      .padding(.top, 4)
      .padding(.bottom, 24)
    }
    .sheet(item: $personalEditor) { target in
      PersonalItemEditorSheet(
        date: day.date,
        item: target.item,
        onSave: { title, notes, start, end, rangeStart, rangeEnd in
          try await onSavePersonalItem(target.item, title, notes, start, end, rangeStart, rangeEnd)
        },
        onDelete: {
          guard let item = target.item else { return }
          try await onDeletePersonalItem(item)
        }
      )
    }
    .sheet(item: $selectedMeeting) { detail in
      CalNavigation {
        ScrollView {
          VStack(alignment: .leading, spacing: 12) {
            Text(detail.item.title).font(.title3.weight(.bold))
            Text(detail.date.formatted(.dateTime.weekday(.wide).month(.wide).day()))
              .foregroundStyle(.secondary)
            if !detail.item.timeRange.isEmpty {
              Text(detail.item.timeRange).font(.subheadline.weight(.semibold))
            }
            if !detail.item.subtitle.isEmpty {
              Text(detail.item.subtitle).font(.body)
            }
          }
          .frame(maxWidth: .infinity, alignment: .leading)
          .padding(20)
        }
        .navigationTitle("Meeting")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
          ToolbarItem(placement: .confirmationAction) {
            Button("Done") { selectedMeeting = nil }
          }
        }
      }
    }
  }

  private func meetingPreview(_ detail: MeetingDetail, label: String) -> some View {
    Button {
      selectedMeeting = detail
    } label: {
      DayAgendaRow(
        systemImage: "person.2.fill",
        title: detail.item.title,
        subtitle: [label, detail.item.timeRange].filter { !$0.isEmpty }.joined(separator: " · ")
      )
    }
    .buttonStyle(.plain)
  }
}

private struct PersonalItemEditorSheet: View {
  let date: Date
  let item: PersonalCalendarItem?
  let onSave: (String, String, String?, String?, Date, Date) async throws -> Void
  let onDelete: () async throws -> Void

  @Environment(\.dismiss) private var dismiss
  @State private var selectedType: String = PersonalItemPresets.titles[0]
  @State private var customTitle: String = ""
  @State private var notes: String = ""
  @State private var startDate: Date
  @State private var endDate: Date
  @State private var hasTime = false
  @State private var startTime = Date()
  @State private var endTime = Date()
  @State private var isSaving = false
  @State private var errorMessage: String?

  init(
    date: Date,
    item: PersonalCalendarItem?,
    onSave: @escaping (String, String, String?, String?, Date, Date) async throws -> Void,
    onDelete: @escaping () async throws -> Void
  ) {
    self.date = date
    self.item = item
    self.onSave = onSave
    self.onDelete = onDelete
    let seed = Calendar.current.startOfDay(for: date)
    _startDate = State(initialValue: seed)
    _endDate = State(initialValue: seed)
  }

  private var isEditing: Bool { item != nil }

  private var resolvedTitle: String {
    if selectedType == PersonalItemPresets.other {
      return customTitle.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    return selectedType
  }

  private var canSave: Bool {
    !resolvedTitle.isEmpty && !isSaving && endDate >= Calendar.current.startOfDay(for: startDate)
  }

  private var rangeSummary: String {
    let start = startDate.formatted(.dateTime.month(.abbreviated).day().year())
    if Calendar.current.isDate(startDate, inSameDayAs: endDate) {
      return start
    }
    let end = endDate.formatted(.dateTime.month(.abbreviated).day().year())
    let days = (Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: startDate), to: Calendar.current.startOfDay(for: endDate)).day ?? 0) + 1
    return "\(start) – \(end) · \(days) days"
  }

  var body: some View {
    CalNavigation {
      Form {
        if isEditing {
          Section {
            Text(date.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()))
              .foregroundStyle(.secondary)
          }
        } else {
          Section {
            DatePicker("Start", selection: $startDate, displayedComponents: .date)
            DatePicker("End", selection: $endDate, displayedComponents: .date)
            Text(rangeSummary)
              .font(.caption)
              .foregroundStyle(.secondary)
          } header: {
            Text("Dates")
          } footer: {
            Text("Same as time off — pick a range to place this personal item on each day.")
          }
        }

        Section {
          Picker("Type", selection: $selectedType) {
            ForEach(PersonalItemPresets.titles, id: \.self) { row in
              Text(row).tag(row)
            }
          }
          .font(.subheadline)

          if selectedType == PersonalItemPresets.other {
            TextField("Title", text: $customTitle)
          }

          TextField("Notes (optional)", text: $notes)
        }

        Section("Time (optional)") {
          Toggle("Add time", isOn: $hasTime)
          if hasTime {
            DatePicker("Start", selection: $startTime, displayedComponents: .hourAndMinute)
            DatePicker("End", selection: $endTime, displayedComponents: .hourAndMinute)
          }
        }

        if let errorMessage {
          Section {
            Text(errorMessage)
              .font(.caption.weight(.semibold))
              .foregroundStyle(ClinicalPalette.warningText)
          }
        }
      }
      .navigationTitle(item == nil ? "Add Personal Item" : "Edit Personal Item")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { dismiss() }
            .disabled(isSaving)
        }
        ToolbarItem(placement: .confirmationAction) {
          Button(item == nil ? "Add" : "Save") {
            Task { await save() }
          }
          .disabled(!canSave)
        }
      }
      .safeAreaInset(edge: .bottom) {
        if item != nil {
          Button(role: .destructive) {
            Task { await deleteItem() }
          } label: {
            Text("Delete personal item")
              .font(.subheadline.weight(.bold))
              .frame(maxWidth: .infinity)
              .padding(.vertical, 12)
          }
          .buttonStyle(.bordered)
          .disabled(isSaving)
          .padding()
        }
      }
      .onAppear {
        let existing = (item?.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if existing.isEmpty {
          selectedType = PersonalItemPresets.titles[0]
          customTitle = ""
        } else if PersonalItemPresets.titles.contains(existing), existing != PersonalItemPresets.other {
          selectedType = existing
          customTitle = ""
        } else {
          selectedType = PersonalItemPresets.other
          customTitle = existing
        }
        notes = item?.notes ?? ""
        hasTime = !(item?.start ?? "").isEmpty
        startTime = Self.dateForTime(item?.start ?? "07:00")
        endTime = Self.dateForTime(item?.end.isEmpty == false ? item!.end : "08:00")
      }
      .onChange(of: startDate) { newValue in
        let day = Calendar.current.startOfDay(for: newValue)
        startDate = day
        if endDate < day {
          endDate = day
        }
      }
      .onChange(of: endDate) { newValue in
        let day = Calendar.current.startOfDay(for: newValue)
        endDate = day
        if day < Calendar.current.startOfDay(for: startDate) {
          startDate = day
        }
      }
    }
  }

  private func save() async {
    let trimmed = resolvedTitle
    guard !trimmed.isEmpty else { return }
    isSaving = true
    errorMessage = nil
    defer { isSaving = false }
    do {
      try await onSave(
        trimmed,
        notes.trimmingCharacters(in: .whitespacesAndNewlines),
        hasTime ? Self.hhmm(startTime) : nil,
        hasTime ? Self.hhmm(endTime) : nil,
        Calendar.current.startOfDay(for: isEditing ? date : startDate),
        Calendar.current.startOfDay(for: isEditing ? date : endDate)
      )
      dismiss()
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  private func deleteItem() async {
    isSaving = true
    errorMessage = nil
    defer { isSaving = false }
    do {
      try await onDelete()
      dismiss()
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  private static func hhmm(_ date: Date) -> String {
    let formatter = DateFormatter()
    formatter.dateFormat = "HH:mm"
    return formatter.string(from: date)
  }

  private static func dateForTime(_ value: String) -> Date {
    let parts = value.split(separator: ":").compactMap { Int($0) }
    var components = Calendar.current.dateComponents([.year, .month, .day], from: Date())
    components.hour = parts.first ?? 7
    components.minute = parts.count > 1 ? parts[1] : 0
    return Calendar.current.date(from: components) ?? Date()
  }
}

private enum PersonalItemPresets {
  static let other = "Other"
  /// Same idea as Time Off’s Type picker — pick from the list, or Other for a custom title.
  static let titles = [
    "Personal appointment",
    "Doctor appointment",
    "Dental",
    "Family",
    "Kids / school",
    "Travel",
    "Errand",
    other,
  ]
}
