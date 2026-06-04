import SwiftUI

struct CALNativeRootView: View {
  @StateObject private var store = NativeScheduleStore()

  var body: some View {
    Group {
      if !store.hasBootstrapped {
        ProgressView("Loading CAL...")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if store.sessionToken == nil {
        NativeAuthView(store: store)
      } else {
        CALNativeTabShell(store: store)
      }
    }
    .task {
      await store.bootstrapLookahead(containing: Date())
    }
  }
}

struct ScheduleHomeView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection
  @State private var scope: ScheduleScope = .day
  @State private var selectedDate = Date()
  @State private var showingDatePicker = false
  @State private var coveringAssignment: ScheduleAssignment?

  private var selectedDay: ScheduleDay {
    store.day(for: selectedDate) ?? ScheduleFixtures.day(for: selectedDate)
  }

  private var visibleWeek: [ScheduleDay] {
    store.week(containing: selectedDate)
  }

  private var visibleMonth: [MonthCell] {
    store.month(containing: selectedDate)
  }

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        VStack(spacing: 0) {
          Picker("Schedule View", selection: $scope) {
            ForEach(ScheduleScope.allCases) { option in
              Text(option.rawValue).tag(option)
            }
          }
          .pickerStyle(.segmented)
          .padding(.horizontal, 16)
          .padding(.top, 8)
          .padding(.bottom, 10)
          .background(.ultraThinMaterial)

          if scope == .day {
            DayScheduleDashboard(
              day: selectedDay,
              days: store.days,
              statusMessage: nonSyncedStatusMessage,
              previousAction: { shiftSelection(by: -1) },
              nextAction: { shiftSelection(by: 1) },
              coverAction: { assignment in
                coveringAssignment = assignment
              }
            )
            .transition(.opacity.combined(with: .move(edge: .trailing)))
          } else {
            ScrollView {
              VStack(alignment: .leading, spacing: 8) {
                if let statusMessage = nonSyncedStatusMessage {
                  Label(statusMessage, systemImage: store.sessionToken == nil ? "lock" : "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
                }

                switch scope {
                case .day:
                  EmptyView()
                case .week:
                  CompactRangeHeader(
                    title: "Week",
                    subtitle: "\(visibleWeek.first?.date.formatted(.dateTime.month(.abbreviated).day()) ?? "") - \(visibleWeek.last?.date.formatted(.dateTime.month(.abbreviated).day().year()) ?? "")",
                    previousAction: { shiftSelection(by: -7) },
                    nextAction: { shiftSelection(by: 7) }
                  )

                  VStack(spacing: 7) {
                    ForEach(visibleWeek) { day in
                      CompactWeekDayCard(
                        day: day,
                        selectedDate: $selectedDate,
                        scope: $scope,
                        coverAction: { assignment in
                          coveringAssignment = assignment
                        }
                      )
                    }
                  }
                case .month:
                  CompactRangeHeader(
                    title: selectedDate.formatted(.dateTime.month(.wide).year()),
                    subtitle: "Month scan",
                    previousAction: { shiftSelection(byMonths: -1) },
                    nextAction: { shiftSelection(byMonths: 1) }
                  )

                  MonthGridView(
                    cells: visibleMonth,
                    selectedDate: $selectedDate,
                    scope: $scope,
                    coverAction: { assignment in
                      coveringAssignment = assignment
                    }
                  )
                    .padding(.horizontal, 10)
                    .padding(.vertical, 10)
                    .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.cardStrong)
                }
              }
              .padding(.horizontal, 16)
              .padding(.top, 8)
              .padding(.bottom, 18)
            }
          }
        }
      }
      .navigationTitle("Schedule")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .navigationBarLeading) {
          Button {
            withAnimation(.snappy(duration: 0.2)) {
              selectedDate = Date()
            }
          } label: {
            Text("Today")
          }
        }

        ToolbarItem(placement: .principal) {
          CALNativeTitleMenu(selectedSection: $selectedSection, store: store)
        }

        ToolbarItemGroup(placement: .navigationBarTrailing) {
          Button {
            showingDatePicker = true
          } label: {
            Image(systemName: "calendar.badge.clock")
          }

          Button {
            Task {
              await loadCurrentScope()
            }
          } label: {
            Image(systemName: "arrow.clockwise")
          }
        }
      }
      .sheet(isPresented: $showingDatePicker) {
        NavigationView {
          DatePicker("Schedule Date", selection: $selectedDate, displayedComponents: .date)
            .datePickerStyle(.graphical)
            .padding()
            .navigationTitle("Choose Date")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
              ToolbarItem(placement: .confirmationAction) {
                Button("Done") {
                  showingDatePicker = false
                }
              }
          }
        }
      }
      .sheet(item: $coveringAssignment) { assignment in
        CallCoverageSheet(
          assignment: assignment,
          currentSurgeon: store.currentSurgeon,
          surgeons: store.eligibleCoveringSurgeons(for: assignment),
          isSaving: store.isLoading,
          saveAction: { surgeon in
            Task {
              do {
                try await store.submitCallCoverage(
                  assignment: assignment,
                  coveringSurgeon: surgeon,
                  selectedDate: selectedDate,
                  scope: scope
                )
                coveringAssignment = nil
              } catch {
                store.setStatusMessage(error.localizedDescription)
              }
            }
          },
          cancelAction: {
            coveringAssignment = nil
          }
        )
      }
      .onChange(of: selectedDate) { nextDate in
        Task {
          await loadCurrentScope(containing: nextDate)
        }
      }
      .onChange(of: scope) { nextScope in
        Task {
          if nextScope == .day {
            await store.loadLookahead(containing: selectedDate)
          } else {
            await store.load(containing: selectedDate, scope: nextScope)
          }
        }
      }
    }
  }

  private func shiftSelection(by days: Int) {
    withAnimation(.snappy(duration: 0.2)) {
      selectedDate = Calendar.current.date(byAdding: .day, value: days, to: selectedDate) ?? selectedDate
    }
  }

  private func shiftSelection(byMonths months: Int) {
    withAnimation(.snappy(duration: 0.2)) {
      selectedDate = Calendar.current.date(byAdding: .month, value: months, to: selectedDate) ?? selectedDate
    }
  }

  private func loadCurrentScope(containing date: Date? = nil) async {
    let targetDate = date ?? selectedDate
    if scope == .day {
      await store.loadLookahead(containing: targetDate)
    } else {
      await store.load(containing: targetDate, scope: scope)
    }
  }

  private var nonSyncedStatusMessage: String? {
    guard let statusMessage = store.statusMessage, !statusMessage.hasPrefix("Synced") else {
      return nil
    }
    return statusMessage
  }
}

private struct DayScheduleSections: View {
  let day: ScheduleDay

  var body: some View {
    Section {
      ScheduleDailyGlanceCard(day: day)
    }
    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 6, trailing: 16))
    .listRowBackground(Color.clear)

    Section("My Schedule") {
      ForEach(day.mySchedule) { item in
        MyScheduleRow(item: item)
      }
    }
    .listRowBackground(Color.white.opacity(0.68))

    Section("Meetings") {
      if day.meetings.isEmpty {
        Label("No meetings", systemImage: "checkmark.circle")
          .font(.subheadline)
          .foregroundStyle(.secondary)
      } else {
        ForEach(day.meetings) { meeting in
          MeetingRow(item: meeting)
        }
      }
    }
    .listRowBackground(Color.white.opacity(0.68))

    Section("Personal Items") {
      if day.personalItems.isEmpty {
        Label("No personal items", systemImage: "checkmark.circle")
          .font(.subheadline)
          .foregroundStyle(.secondary)
      } else {
        ForEach(day.personalItems, id: \.self) { item in
          Label(item, systemImage: "note.text")
            .font(.subheadline)
        }
      }
    }
    .listRowBackground(Color.white.opacity(0.68))
  }
}

struct MyScheduleRow: View {
  let item: DoctorScheduleItem

  var body: some View {
    HStack(spacing: 10) {
      Text(item.period)
        .font(.caption2.weight(.bold))
        .foregroundStyle(ClinicalPalette.teal)
        .frame(width: 28, alignment: .leading)

      VStack(alignment: .leading, spacing: 2) {
        Text(item.title)
          .font(.subheadline.weight(.semibold))
        if !item.subtitle.isEmpty {
          Text(item.subtitle)
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      Spacer()

      if !item.timeRange.isEmpty {
        Text(item.timeRange)
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)
      }
    }
    .padding(.vertical, 1)
  }
}

private struct MeetingRow: View {
  let item: DoctorScheduleItem

  var body: some View {
    HStack(spacing: 10) {
      Image(systemName: "person.2.wave.2")
        .font(.caption)
        .foregroundStyle(ClinicalPalette.teal)
        .frame(width: 20)

      VStack(alignment: .leading, spacing: 2) {
        Text(item.title)
          .font(.subheadline.weight(.semibold))
        if !item.subtitle.isEmpty {
          Text(item.subtitle)
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      Spacer()

      if !item.timeRange.isEmpty {
        Text(item.timeRange)
          .font(.caption2.weight(.semibold))
          .foregroundStyle(.secondary)
      }
    }
    .padding(.vertical, 1)
  }
}

struct ScheduleDailyGlanceCard: View {
  let day: ScheduleDay
  var coverAction: ((ScheduleAssignment) -> Void)?

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text("On Call")
        .font(.caption.weight(.semibold))
        .foregroundStyle(.secondary)

      if !day.assignments.isEmpty {
        Divider().opacity(0.45)
        VStack(spacing: 8) {
          ForEach(day.assignments) { assignment in
            GlanceOnCallLine(assignment: assignment, coverAction: coverAction)
          }
        }
      }
    }
    .padding(14)
    .liquidGlassCard(cornerRadius: 18, tint: ClinicalPalette.tealSoft)
  }
}

private struct GlanceOnCallLine: View {
  let assignment: ScheduleAssignment
  var coverAction: ((ScheduleAssignment) -> Void)?

  var body: some View {
    Button {
      coverAction?(assignment)
    } label: {
      HStack(spacing: 10) {
        Image(systemName: assignment.systemImage)
          .font(.body)
          .foregroundStyle(ClinicalPalette.teal)
          .frame(width: 22)

        VStack(alignment: .leading, spacing: 2) {
          Text(assignment.locationShort)
            .font(.subheadline.weight(.semibold))
        }

        Spacer()

        CoverageInitialsView(assignment: assignment)

        if assignment.rotationId != nil {
          Image(systemName: "chevron.right")
            .font(.caption2.weight(.bold))
            .foregroundStyle(.tertiary)
        }
      }
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .disabled(coverAction == nil || assignment.rotationId == nil)
  }
}

private struct CoverageInitialsView: View {
  let assignment: ScheduleAssignment

  var body: some View {
    if assignment.isCovered {
      HStack(spacing: 5) {
        StruckInitialsText(
          text: assignment.originalInitials,
          font: .system(.body, design: .monospaced).weight(.semibold)
        )

        Text(assignment.coveringInitials ?? assignment.surgeon)
          .font(.system(.body, design: .monospaced).weight(.semibold))
          .foregroundStyle(.primary)
      }
    } else {
      Text(assignment.surgeon)
        .font(.system(.body, design: .monospaced).weight(.semibold))
        .foregroundStyle(.primary)
    }
  }
}

private struct StruckInitialsText: View {
  let text: String
  let font: Font

  var body: some View {
    Text(text)
      .font(font)
      .foregroundStyle(.red)
      .overlay(alignment: .center) {
        Rectangle()
          .fill(.red)
          .frame(height: 1.4)
      }
  }
}

private struct CallCoverageSheet: View {
  let assignment: ScheduleAssignment
  let currentSurgeon: NativeSurgeon?
  let surgeons: [NativeSurgeon]
  let isSaving: Bool
  let saveAction: (NativeSurgeon) -> Void
  let cancelAction: () -> Void

  @State private var selectedSurgeonId: Int?

  private var selectedSurgeon: NativeSurgeon? {
    surgeons.first { $0.id == selectedSurgeonId } ?? surgeons.first
  }

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        VStack(alignment: .leading, spacing: 12) {
          VStack(alignment: .leading, spacing: 6) {
            Text(assignment.locationShort)
              .font(.headline.weight(.semibold))
            HStack(spacing: 6) {
              if assignment.isCovered {
                StruckInitialsText(
                  text: assignment.originalInitials,
                  font: .system(.title3, design: .monospaced).weight(.bold)
                )
              } else {
                Text(assignment.originalInitials)
                  .font(.system(.title3, design: .monospaced).weight(.bold))
                  .foregroundStyle(.red)
              }
              Image(systemName: "arrow.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(.secondary)
              Text(selectedSurgeon?.initials ?? currentSurgeon?.initials ?? "Me")
                .font(.system(.title3, design: .monospaced).weight(.bold))
                .foregroundStyle(.primary)
            }
          }
          .padding(14)
          .frame(maxWidth: .infinity, alignment: .leading)
          .liquidGlassCard(cornerRadius: 18, tint: ClinicalPalette.cardStrong)

          if surgeons.isEmpty {
            EmptyDashboardRow(title: "No eligible covering surgeons loaded")
              .padding(14)
              .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.amber)
          } else {
            ScrollView {
              VStack(spacing: 8) {
                ForEach(surgeons) { surgeon in
                  Button {
                    selectedSurgeonId = surgeon.id
                  } label: {
                    HStack(spacing: 10) {
                      Text(surgeon.initials)
                        .font(.system(.subheadline, design: .monospaced).weight(.bold))
                        .foregroundStyle(ClinicalPalette.teal)
                        .frame(width: 42, alignment: .leading)

                      VStack(alignment: .leading, spacing: 2) {
                        Text(surgeon.name)
                          .font(.subheadline.weight(.semibold))
                          .foregroundStyle(.primary)
                        Text(surgeon.staffType == "physician" ? "Surgeon" : "PA / Staff")
                          .font(.caption2)
                          .foregroundStyle(.secondary)
                      }

                      Spacer()

                      if selectedSurgeonId == surgeon.id {
                        Image(systemName: "checkmark.circle.fill")
                          .foregroundStyle(ClinicalPalette.teal)
                      }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .liquidGlassCard(
                      cornerRadius: 15,
                      tint: selectedSurgeonId == surgeon.id ? ClinicalPalette.tealSoft : Color.white.opacity(0.62)
                    )
                  }
                  .buttonStyle(.plain)
                }
              }
            }
          }

          Button {
            if let selectedSurgeon {
              saveAction(selectedSurgeon)
            }
          } label: {
            HStack {
              Spacer()
              if isSaving {
                ProgressView()
              } else {
                Text("Save Coverage")
                  .font(.subheadline.weight(.semibold))
              }
              Spacer()
            }
            .padding(.vertical, 12)
            .background(ClinicalPalette.teal, in: RoundedRectangle(cornerRadius: 14))
            .foregroundStyle(.white)
          }
          .disabled(selectedSurgeon == nil || isSaving)
        }
        .padding(16)
      }
      .navigationTitle("Cover On Call")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel", action: cancelAction)
        }
      }
    }
    .onAppear {
      selectedSurgeonId = currentSurgeon.flatMap { current in
        surgeons.contains { $0.id == current.id } ? current.id : nil
      } ?? surgeons.first?.id
    }
  }
}

private struct ScheduleMetricPill: View {
  let title: String
  let systemImage: String

  var body: some View {
    Label(title, systemImage: systemImage)
      .font(.caption.weight(.semibold))
      .padding(.horizontal, 10)
      .padding(.vertical, 7)
      .background(Color.white.opacity(0.56), in: Capsule())
      .foregroundStyle(ClinicalPalette.teal)
  }
}

private struct ScheduleDateSummary: View {
  let day: ScheduleDay

  var body: some View {
    HStack(spacing: 12) {
      VStack(spacing: 1) {
        Text(day.date.formatted(.dateTime.weekday(.abbreviated)))
          .font(.caption.weight(.bold))
          .foregroundStyle(.secondary)
        Text(day.date.formatted(.dateTime.day()))
          .font(.title2.weight(.semibold))
      }
      .frame(width: 46)

      VStack(alignment: .leading, spacing: 3) {
        Text(day.date.formatted(.dateTime.weekday(.wide).month(.abbreviated).day().year()))
          .font(.headline)
        Text(day.summary)
          .font(.subheadline)
          .foregroundStyle(.secondary)
      }

      Spacer()
    }
    .padding(.vertical, 4)
  }
}

private struct ScheduleRangeHeader: View {
  let title: String
  let subtitle: String
  let previousAction: () -> Void
  let nextAction: () -> Void

  var body: some View {
    HStack {
      VStack(alignment: .leading, spacing: 3) {
        Text(title)
          .font(.headline)
        Text(subtitle)
          .font(.subheadline)
          .foregroundStyle(.secondary)
      }

      Spacer()

      HStack(spacing: 14) {
        Button(action: previousAction) {
          Image(systemName: "chevron.left")
        }

        Button(action: nextAction) {
          Image(systemName: "chevron.right")
        }
      }
      .font(.headline)
    }
    .padding(.vertical, 4)
  }
}

private struct CompactRangeHeader: View {
  let title: String
  let subtitle: String
  let previousAction: () -> Void
  let nextAction: () -> Void

  var body: some View {
    HStack {
      VStack(alignment: .leading, spacing: 2) {
        Text(title)
          .font(.subheadline.weight(.semibold))
        Text(subtitle)
          .font(.caption2)
          .foregroundStyle(.secondary)
      }

      Spacer()

      HStack(spacing: 10) {
        Button(action: previousAction) {
          Image(systemName: "chevron.left")
        }

        Button(action: nextAction) {
          Image(systemName: "chevron.right")
        }
      }
      .font(.subheadline.weight(.semibold))
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 9)
    .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.cardStrong)
  }
}

private struct CompactWeekDayCard: View {
  let day: ScheduleDay
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope
  let coverAction: (ScheduleAssignment) -> Void

  var body: some View {
    HStack(alignment: .top, spacing: 10) {
      VStack(spacing: 1) {
        Text(day.date.formatted(.dateTime.weekday(.abbreviated)))
          .font(.caption2.weight(.bold))
          .foregroundStyle(.secondary)
        Text(day.date.formatted(.dateTime.day()))
          .font(.subheadline.weight(.bold))
          .foregroundStyle(Calendar.current.isDateInToday(day.date) ? ClinicalPalette.teal : ClinicalPalette.ink)
      }
      .frame(width: 34)
      .contentShape(Rectangle())
      .onTapGesture {
        openDay()
      }

      VStack(alignment: .leading, spacing: 6) {
        ScheduleAssignmentActionLine(
          prefix: "ON",
          assignments: Array(day.assignments.prefix(3)),
          tint: ClinicalPalette.teal,
          action: coverAction
        )

        ScheduleStatusLine(
          prefix: "OFF",
          value: day.off.prefix(4).joined(separator: " / "),
          tint: ClinicalPalette.teal
        )
      }
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 9)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 16, tint: Calendar.current.isDateInToday(day.date) ? ClinicalPalette.tealSoft : ClinicalPalette.card)
  }

  private func openDay() {
    withAnimation(.snappy(duration: 0.22)) {
      selectedDate = day.date
      scope = .day
    }
  }
}

private struct ScheduleAssignmentActionLine: View {
  let prefix: String
  let assignments: [ScheduleAssignment]
  let tint: Color
  let action: (ScheduleAssignment) -> Void

  var body: some View {
    HStack(spacing: 6) {
      Text(prefix)
        .font(.caption2.weight(.bold))
        .foregroundStyle(tint)
        .frame(width: 28, alignment: .leading)

      if assignments.isEmpty {
        Text("None")
          .font(.caption.weight(.medium))
          .foregroundStyle(.secondary)
      } else {
        HStack(spacing: 4) {
          ForEach(assignments) { assignment in
            Button {
              action(assignment)
            } label: {
              SmallCoverageInitialsView(assignment: assignment)
            }
            .buttonStyle(.plain)
            .disabled(assignment.rotationId == nil)
          }
        }
      }
    }
    .frame(maxWidth: .infinity, alignment: .leading)
  }
}

private struct SmallCoverageInitialsView: View {
  let assignment: ScheduleAssignment

  var body: some View {
    if assignment.isCovered {
      HStack(spacing: 2) {
        StruckInitialsText(
          text: assignment.originalInitials,
          font: .system(.caption, design: .rounded).weight(.semibold)
        )
        Text(assignment.coveringInitials ?? assignment.surgeon)
          .font(.system(.caption, design: .rounded).weight(.semibold))
          .foregroundStyle(.primary)
      }
      .padding(.horizontal, 3)
      .padding(.vertical, 1)
      .background(ClinicalPalette.teal.opacity(0.08), in: Capsule())
    } else {
      Text(assignment.surgeon)
        .font(.system(.caption, design: .rounded).weight(.semibold))
        .foregroundStyle(.primary)
        .padding(.horizontal, 4)
        .padding(.vertical, 1)
        .background(ClinicalPalette.teal.opacity(0.08), in: Capsule())
    }
  }
}

private struct LegacyCompactWeekDayCard: View {
  let day: ScheduleDay
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope

  var body: some View {
    Button {
      withAnimation(.snappy(duration: 0.22)) {
        selectedDate = day.date
        scope = .day
      }
    } label: {
      HStack(alignment: .top, spacing: 10) {
        VStack(spacing: 1) {
          Text(day.date.formatted(.dateTime.weekday(.abbreviated)))
            .font(.caption2.weight(.bold))
            .foregroundStyle(.secondary)
          Text(day.date.formatted(.dateTime.day()))
            .font(.subheadline.weight(.bold))
            .foregroundStyle(Calendar.current.isDateInToday(day.date) ? ClinicalPalette.teal : ClinicalPalette.ink)
        }
        .frame(width: 34)

        VStack(alignment: .leading, spacing: 6) {
          ScheduleStatusLine(
            prefix: "ON",
            value: day.assignments.map(\.surgeon).prefix(3).joined(separator: " / "),
            tint: ClinicalPalette.teal
          )

          ScheduleStatusLine(
            prefix: "OFF",
            value: day.off.prefix(4).joined(separator: " / "),
          tint: ClinicalPalette.teal
          )
        }
      }
      .padding(.horizontal, 12)
      .padding(.vertical, 9)
      .frame(maxWidth: .infinity, alignment: .leading)
      .liquidGlassCard(cornerRadius: 16, tint: Calendar.current.isDateInToday(day.date) ? ClinicalPalette.tealSoft : ClinicalPalette.card)
    }
    .buttonStyle(.plain)
  }
}

private struct WeekDaySection: View {
  let day: ScheduleDay
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope

  var body: some View {
    Section {
      Button {
        selectedDate = day.date
        scope = .day
      } label: {
        VStack(alignment: .leading, spacing: 10) {
          HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
              Text(day.date.formatted(.dateTime.weekday(.wide)))
                .font(.headline)
              Text(day.date.formatted(.dateTime.month(.abbreviated).day()))
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer()

            if !day.off.isEmpty {
              FlowLine(items: day.off)
            }
          }

          ForEach(day.assignments) { assignment in
            CompactAssignmentLine(assignment: assignment)
          }

          if !day.personalItems.isEmpty {
            Label(day.personalItems.joined(separator: ", "), systemImage: "note.text")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
        }
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
    }
  }
}

private struct AssignmentRow: View {
  let assignment: ScheduleAssignment

  var body: some View {
    HStack(spacing: 12) {
      Image(systemName: assignment.systemImage)
        .foregroundStyle(ClinicalPalette.teal)
        .frame(width: 28)

      VStack(alignment: .leading, spacing: 3) {
        Text(assignment.location)
          .font(.body)
        Text(assignment.time)
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      Spacer()

      Text(assignment.surgeon)
        .font(.system(.headline, design: .monospaced))
        .foregroundStyle(.primary)
    }
    .padding(.vertical, 3)
  }
}

private struct CompactAssignmentLine: View {
  let assignment: ScheduleAssignment

  var body: some View {
    HStack(spacing: 8) {
      Text(assignment.locationShort)
        .font(.caption.weight(.semibold))
        .foregroundStyle(.primary)
      Spacer()
      Text(assignment.surgeon)
        .font(.system(.caption, design: .monospaced).weight(.semibold))
        .foregroundStyle(.secondary)
    }
  }
}

private struct ScheduleStatusLine: View {
  let prefix: String
  let value: String
  let tint: Color

  var body: some View {
    HStack(spacing: 6) {
      Text(prefix)
        .font(.caption2.weight(.bold))
        .foregroundStyle(tint)
        .frame(width: 28, alignment: .leading)

      if value.isEmpty {
        Text("None")
          .font(.caption.weight(.medium))
          .foregroundStyle(.secondary)
      } else {
        Text(value)
          .font(.system(.caption, design: .rounded).weight(.semibold))
          .foregroundStyle(.primary)
          .lineLimit(1)
          .minimumScaleFactor(0.72)
      }
    }
    .frame(maxWidth: .infinity, alignment: .leading)
  }
}

struct FlowLine: View {
  let items: [String]

  var body: some View {
    HStack(spacing: 5) {
      ForEach(items, id: \.self) { item in
        Text(item)
          .font(.caption2.weight(.semibold))
          .padding(.horizontal, 8)
          .padding(.vertical, 4)
          .background(ClinicalPalette.porcelainChip.opacity(0.94), in: Capsule())
          .overlay {
            Capsule()
              .stroke(ClinicalPalette.scrubInk.opacity(0.26), lineWidth: 0.75)
          }
          .foregroundStyle(ClinicalPalette.scrubInk)
      }
    }
  }
}

private struct MonthGridView: View {
  let cells: [MonthCell]
  @Binding var selectedDate: Date
  @Binding var scope: ScheduleScope
  let coverAction: (ScheduleAssignment) -> Void

  private let columns = Array(repeating: GridItem(.flexible(), spacing: 6), count: 7)

  var body: some View {
    VStack(spacing: 10) {
      LazyVGrid(columns: columns, spacing: 6) {
        ForEach(Calendar.current.shortWeekdaySymbols, id: \.self) { day in
          Text(String(day.prefix(1)))
            .font(.caption2.weight(.bold))
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity)
        }

        ForEach(cells) { cell in
          MonthCellView(
            cell: cell,
            openDayAction: {
              withAnimation(.snappy(duration: 0.22)) {
                selectedDate = cell.date
                scope = .day
              }
            },
            coverAction: coverAction
          )
        }
      }
    }
    .padding(.vertical, 6)
  }
}

private struct MonthCellView: View {
  let cell: MonthCell
  let openDayAction: () -> Void
  let coverAction: (ScheduleAssignment) -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 3) {
      Button(action: openDayAction) {
        Text(cell.date.formatted(.dateTime.day()))
          .font(.caption2.weight(.bold))
          .foregroundStyle(cell.isCurrentMonth ? .primary : .secondary)
          .frame(maxWidth: .infinity, alignment: .leading)
      }
      .buttonStyle(.plain)

      MonthCellLabel(prefix: "OFF", value: cell.offSummary, tint: ClinicalPalette.teal)
      MonthCallLabel(assignments: Array(cell.assignments.prefix(2)), action: coverAction)
    }
    .padding(.horizontal, 4)
    .padding(.vertical, 5)
    .frame(maxWidth: .infinity, minHeight: 62, alignment: .topLeading)
    .background(cellBackground, in: RoundedRectangle(cornerRadius: 9))
    .overlay {
      RoundedRectangle(cornerRadius: 9)
        .stroke(cell.isToday ? ClinicalPalette.teal.opacity(0.55) : Color.white.opacity(0.58), lineWidth: cell.isToday ? 1.1 : 0.7)
    }
  }

  private var cellBackground: Color {
    if cell.isToday {
      return ClinicalPalette.tealSoft.opacity(0.82)
    }
    if !cell.isCurrentMonth {
      return Color.white.opacity(0.42)
    }
    return ClinicalPalette.card.opacity(0.74)
  }
}

private struct MonthCallLabel: View {
  let assignments: [ScheduleAssignment]
  let action: (ScheduleAssignment) -> Void

  var body: some View {
    if assignments.isEmpty {
      Text(" ")
        .font(.system(size: 9, weight: .semibold, design: .rounded))
        .frame(height: 13)
    } else {
      HStack(spacing: 2) {
        Text("ON")
          .font(.system(size: 9, weight: .semibold, design: .rounded))
          .foregroundStyle(ClinicalPalette.teal)

        ForEach(assignments) { assignment in
          Button {
            action(assignment)
          } label: {
            Text(assignment.surgeon)
              .font(.system(size: 9, weight: .semibold, design: .rounded))
              .foregroundStyle(ClinicalPalette.teal)
              .lineLimit(1)
          }
          .buttonStyle(.plain)
          .disabled(assignment.rotationId == nil)
        }
      }
      .minimumScaleFactor(0.55)
      .padding(.horizontal, 3)
      .padding(.vertical, 2)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(ClinicalPalette.teal.opacity(0.11), in: RoundedRectangle(cornerRadius: 4))
    }
  }
}

private struct MonthCellLabel: View {
  let prefix: String
  let value: String
  let tint: Color

  var body: some View {
    if value.isEmpty {
      Text(" ")
        .font(.system(size: 9, weight: .semibold, design: .rounded))
        .frame(height: 13)
    } else {
      Text("\(prefix) \(value)")
        .font(.system(size: 9, weight: .semibold, design: .rounded))
        .foregroundStyle(tint)
        .lineLimit(1)
        .minimumScaleFactor(0.55)
        .padding(.horizontal, 3)
        .padding(.vertical, 2)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tint.opacity(0.11), in: RoundedRectangle(cornerRadius: 4))
    }
  }
}

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
