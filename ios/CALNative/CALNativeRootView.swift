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

struct StruckInitialsText: View {
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
