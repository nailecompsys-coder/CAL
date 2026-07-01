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
    store.day(for: selectedDate) ?? ScheduleDay.empty(for: selectedDate)
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
              statusMessage: store.warningMessage,
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

}
