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
      } else if store.sessionRole == .scheduler {
        NativeSchedulerShell(store: store)
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
  @Binding var selectedDate: Date
  @State private var scope: ScheduleScope = .day
  @State private var showingDatePicker = false
  @State private var coveringAssignment: ScheduleAssignment?

  private var selectedDay: ScheduleDay {
    store.day(for: selectedDate) ?? ScheduleDay.empty(for: selectedDate)
  }

  private var visibleWeek: [ScheduleDay] {
    store.week(containing: selectedDate)
  }

  private var visibleMonth: [MonthCell] {
    store.month(containing: selectedDate)
  }

  private var stepperTitle: String {
    let calendar = Calendar.current
    switch scope {
    case .day:
      if calendar.isDateInToday(selectedDate) {
        return "Today · \(selectedDate.formatted(.dateTime.month(.abbreviated).day()))"
      }
      return selectedDate.formatted(.dateTime.weekday(.wide).month(.abbreviated).day())
    case .week:
      let start = visibleWeek.first?.date ?? selectedDate
      let end = visibleWeek.last?.date ?? selectedDate
      return "\(start.formatted(.dateTime.month(.abbreviated).day())) – \(end.formatted(.dateTime.month(.abbreviated).day()))"
    case .month:
      return selectedDate.formatted(.dateTime.month(.wide).year())
    }
  }

  private var stepperSubtitle: String? {
    switch scope {
    case .day:
      return selectedDate.formatted(.dateTime.year())
    case .week:
      return "Week"
    case .month:
      return "Month"
    }
  }

  private var isOnTodayRange: Bool {
    let calendar = Calendar.current
    let today = Date()
    switch scope {
    case .day:
      return calendar.isDateInToday(selectedDate)
    case .week:
      return visibleWeek.contains { calendar.isDateInToday($0.date) }
    case .month:
      return calendar.isDate(selectedDate, equalTo: today, toGranularity: .month)
    }
  }

  var body: some View {
    CalNavigation {
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
          .padding(.bottom, 8)
          .background(.ultraThinMaterial)
          .calReadableColumn(ClinicalLayout.wideColumn)

          ScheduleDateStepper(
            title: stepperTitle,
            subtitle: stepperSubtitle,
            previousAction: { stepBackward() },
            nextAction: { stepForward() },
            onTitleTap: { showingDatePicker = true },
            todayAction: { jumpToToday() },
            showsTodayButton: !isOnTodayRange
          )
          .padding(.horizontal, 16)
          .padding(.bottom, 8)
          .calReadableColumn(ClinicalLayout.wideColumn)

          Group {
            if scope == .day {
              DayScheduleDashboard(
                day: selectedDay,
                days: store.days,
                statusMessage: store.warningMessage,
                coverAction: { assignment in
                  coveringAssignment = assignment
                },
                openPatientsAction: {
                  selectedSection = .patients
                }
              )
              .calReadableColumn(ClinicalLayout.contentColumn)
              .transition(.opacity)
            } else {
              ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                  if let statusMessage = store.warningMessage {
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
                    MonthGridView(
                      cells: visibleMonth,
                      selectedDate: $selectedDate,
                      scope: $scope,
                      coverAction: { assignment in
                        coveringAssignment = assignment
                      }
                    )
                    .padding(.horizontal, 8)
                    .padding(.vertical, 8)
                    .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.cardStrong)

                    MonthSelectedDayAgenda(
                      day: selectedDay,
                      openDayAction: {
                        withAnimation(.easeInOut(duration: 0.2)) {
                          scope = .day
                        }
                      },
                      coverAction: { assignment in
                        coveringAssignment = assignment
                      },
                      openPatientsAction: {
                        selectedSection = .patients
                      }
                    )
                    .padding(.top, 4)
                  }
                }
                .padding(.horizontal, 16)
                .padding(.top, 4)
                .padding(.bottom, 18)
                .calReadableColumn(scope == .month ? ClinicalLayout.wideColumn : ClinicalLayout.contentColumn)
              }
              .refreshable {
                await loadCurrentScope()
              }
            }
          }
        }
      }
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .principal) {
          CALNativeTitleMenu(selectedSection: $selectedSection, store: store)
        }

        ToolbarItem(placement: .navigationBarTrailing) {
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
        CalNavigation {
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
                store.setWarningMessage(error.localizedDescription)
              }
            }
          },
          clearCoverageAction: {
            Task {
              do {
                try await store.cancelCallCoverage(
                  assignment: assignment,
                  selectedDate: selectedDate,
                  scope: scope
                )
                coveringAssignment = nil
              } catch {
                store.setWarningMessage(error.localizedDescription)
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

  private func stepBackward() {
    switch scope {
    case .day:
      shiftSelection(by: -1)
    case .week:
      shiftSelection(by: -7)
    case .month:
      shiftSelection(byMonths: -1)
    }
  }

  private func stepForward() {
    switch scope {
    case .day:
      shiftSelection(by: 1)
    case .week:
      shiftSelection(by: 7)
    case .month:
      shiftSelection(byMonths: 1)
    }
  }

  private func shiftSelection(by days: Int) {
    withAnimation(.easeInOut(duration: 0.2)) {
      selectedDate = Calendar.current.date(byAdding: .day, value: days, to: selectedDate) ?? selectedDate
    }
  }

  private func shiftSelection(byMonths months: Int) {
    withAnimation(.easeInOut(duration: 0.2)) {
      selectedDate = Calendar.current.date(byAdding: .month, value: months, to: selectedDate) ?? selectedDate
    }
  }

  private func jumpToToday() {
    withAnimation(.easeInOut(duration: 0.2)) {
      selectedDate = Date()
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
}
