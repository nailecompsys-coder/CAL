import SwiftUI

struct DayScheduleDashboard: View {
  let day: ScheduleDay
  let days: [ScheduleDay]
  let statusMessage: String?
  let coverAction: (ScheduleAssignment) -> Void
  let onSavePersonalItem: (PersonalCalendarItem?, String, String, String?, String?) async throws -> Void
  let onDeletePersonalItem: (PersonalCalendarItem) async throws -> Void

  @State private var personalEditor: PersonalEditorTarget?

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

  private var nextMeeting: (date: Date, content: String)? {
    nextAgendaItem { day in
      day.meetings.first.map(Self.meetingSummary)
    }
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
      VStack(alignment: .leading, spacing: 8) {
        if let statusMessage {
          Label(statusMessage, systemImage: "exclamationmark.triangle")
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
        }

        ScheduleDailyGlanceCard(day: day, coverAction: coverAction)

        DashboardSection(title: "Clinic / OR Schedule", tint: ClinicalPalette.cardStrong) {
          ClinicOrScheduleList(dayId: day.id, items: day.mySchedule)
        }

        DashboardSection(title: "Meetings", tint: ClinicalPalette.meeting) {
          AgendaPreviewRows(
            todayContent: day.meetings.isEmpty ? nil : day.meetings.map(Self.meetingSummary).joined(separator: ", "),
            emptyTodayText: "none",
            nextDate: nextMeeting?.date,
            nextContent: nextMeeting?.content,
            systemImage: "person.2"
          )
        }

        DashboardSection(title: "Personal", tint: ClinicalPalette.mint) {
          VStack(alignment: .leading, spacing: 8) {
            if day.personalItems.isEmpty {
              AgendaPreviewRows(
                todayContent: nil,
                emptyTodayText: "none — add a personal item",
                nextDate: nextPersonal?.date,
                nextContent: nextPersonal?.content,
                systemImage: "note.text"
              )
            } else {
              ForEach(day.personalItems) { item in
                Button {
                  personalEditor = .edit(item)
                } label: {
                  HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: "note.text")
                      .font(.caption.weight(.semibold))
                      .foregroundStyle(ClinicalPalette.teal)
                    VStack(alignment: .leading, spacing: 2) {
                      Text(item.title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ClinicalPalette.ink)
                        .multilineTextAlignment(.leading)
                      if !item.timeRangeLabel.isEmpty {
                        Text(item.timeRangeLabel)
                          .font(.caption.weight(.semibold))
                          .foregroundStyle(.secondary)
                      } else if !item.notes.isEmpty {
                        Text(item.notes)
                          .font(.caption)
                          .foregroundStyle(.secondary)
                          .lineLimit(1)
                      }
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                      .font(.caption2.weight(.bold))
                      .foregroundStyle(.secondary)
                  }
                  .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
              }

              if let nextPersonal {
                AgendaPreviewRow(
                  prefix: nextPersonal.date.formatted(.dateTime.month(.defaultDigits).day()),
                  content: nextPersonal.content,
                  systemImage: "calendar",
                  isMuted: false
                )
              }
            }

            Button {
              personalEditor = .create
            } label: {
              Label("Add personal item", systemImage: "plus.circle.fill")
                .font(.subheadline.weight(.bold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            }
            .buttonStyle(.borderedProminent)
            .tint(ClinicalPalette.teal)
          }
        }
      }
      .padding(.horizontal, 16)
      .padding(.top, 4)
      .padding(.bottom, 18)
    }
    .sheet(item: $personalEditor) { target in
      PersonalItemEditorSheet(
        date: day.date,
        item: target.item,
        onSave: { title, notes, start, end in
          try await onSavePersonalItem(target.item, title, notes, start, end)
        },
        onDelete: {
          guard let item = target.item else { return }
          try await onDeletePersonalItem(item)
        }
      )
    }
  }

  private static func meetingSummary(_ item: DoctorScheduleItem) -> String {
    [item.timeRange, item.title, item.subtitle]
      .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
      .joined(separator: " ")
  }
}

private struct PersonalItemEditorSheet: View {
  let date: Date
  let item: PersonalCalendarItem?
  let onSave: (String, String, String?, String?) async throws -> Void
  let onDelete: () async throws -> Void

  @Environment(\.dismiss) private var dismiss
  @State private var selectedType: String = PersonalItemPresets.titles[0]
  @State private var customTitle: String = ""
  @State private var notes: String = ""
  @State private var hasTime = false
  @State private var startTime = Date()
  @State private var endTime = Date()
  @State private var isSaving = false
  @State private var errorMessage: String?

  private var resolvedTitle: String {
    if selectedType == PersonalItemPresets.other {
      return customTitle.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    return selectedType
  }

  private var canSave: Bool {
    !resolvedTitle.isEmpty && !isSaving
  }

  var body: some View {
    CalNavigation {
      Form {
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
        } header: {
          Text(date.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()))
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
        hasTime ? Self.hhmm(endTime) : nil
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

private struct AgendaPreviewRows: View {
  let todayContent: String?
  let emptyTodayText: String
  let nextDate: Date?
  let nextContent: String?
  let systemImage: String

  var body: some View {
    VStack(alignment: .leading, spacing: 5) {
      AgendaPreviewRow(
        prefix: "Today:",
        content: todayContent ?? emptyTodayText,
        systemImage: systemImage,
        isMuted: todayContent == nil
      )

      if let nextDate, let nextContent, !nextContent.isEmpty {
        AgendaPreviewRow(
          prefix: nextDate.formatted(.dateTime.month(.defaultDigits).day()),
          content: nextContent,
          systemImage: "calendar",
          isMuted: false
        )
      }
    }
  }
}

private struct AgendaPreviewRow: View {
  let prefix: String
  let content: String
  let systemImage: String
  let isMuted: Bool

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 6) {
      Image(systemName: systemImage)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(isMuted ? .secondary : ClinicalPalette.teal)
      Text(prefix)
        .font(.caption.weight(.bold))
        .foregroundStyle(isMuted ? .secondary : ClinicalPalette.ink)
      Text(content)
        .font(.caption)
        .foregroundStyle(isMuted ? .secondary : ClinicalPalette.ink)
        .multilineTextAlignment(.leading)
      Spacer(minLength: 0)
    }
  }
}
