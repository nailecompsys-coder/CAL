import SwiftUI

@MainActor
final class NativeScheduleStore: ObservableObject {
  @Published private(set) var days: [ScheduleDay] = []
  @Published private(set) var timeOffRequests: [TimeOffRequest] = []
  @Published private(set) var currentSurgeon: NativeSurgeon?
  @Published private(set) var surgeons: [NativeSurgeon] = []
  @Published private(set) var patientToday: PatientSummary?
  @Published private(set) var patientUpcoming: [PatientSummary] = []
  @Published private(set) var isLoading = false
  @Published private(set) var statusMessage: String?
  @Published private(set) var sessionToken: String?
  @Published private(set) var hasBootstrapped = false
  @Published private(set) var authBusy = false
  @Published private(set) var authMessage: String?

  private let client = NativeCALClient()

  func bootstrap(containing date: Date, scope: ScheduleScope) async {
    if sessionToken == nil {
      sessionToken = CALKeychain.readSessionToken()
    }
    hasBootstrapped = true
    if sessionToken != nil {
      await load(containing: date, scope: scope)
    }
  }

  func bootstrapLookahead(containing date: Date, daysAhead: Int = 60) async {
    if sessionToken == nil {
      sessionToken = CALKeychain.readSessionToken()
    }
    hasBootstrapped = true
    if sessionToken != nil {
      await loadLookahead(containing: date, daysAhead: daysAhead)
    }
  }

  func load(containing date: Date, scope: ScheduleScope) async {
    guard let token = sessionToken, !token.isEmpty else {
      days = ScheduleFixtures.week(containing: date)
      statusMessage = nil
      return
    }

    isLoading = true
    statusMessage = "Syncing schedule..."
    defer { isLoading = false }

    do {
      let range = DateRange(containing: date, scope: scope)
      let home = try await client.fetchHome(token: token, start: range.start, end: range.end)
      currentSurgeon = home.surgeon
      surgeons = home.surgeons ?? []
      days = home.days.map { $0.scheduleDay }
      timeOffRequests = home.requests.map(\.timeOffRequest)
      patientToday = home.patients?.today.patientSummary
      patientUpcoming = home.patients?.upcoming.map(\.patientSummary) ?? []
      statusMessage = "Synced \(Date().formatted(.dateTime.hour().minute().second()))"
    } catch {
      if days.isEmpty {
        days = ScheduleFixtures.week(containing: date)
      }
      statusMessage = "Live sync failed. Showing preview data. \(error.localizedDescription)"
    }
  }

  func loadLookahead(containing date: Date, daysAhead: Int = 60) async {
    guard let token = sessionToken, !token.isEmpty else {
      days = ScheduleFixtures.week(containing: date)
      statusMessage = nil
      return
    }

    isLoading = true
    statusMessage = "Syncing schedule..."
    defer { isLoading = false }

    do {
      let calendar = Calendar.current
      let start = calendar.startOfDay(for: date)
      let end = calendar.date(byAdding: .day, value: daysAhead, to: start) ?? start
      let home = try await client.fetchHome(token: token, start: start, end: end)
      currentSurgeon = home.surgeon
      surgeons = home.surgeons ?? []
      days = home.days.map { $0.scheduleDay }
      timeOffRequests = home.requests.map(\.timeOffRequest)
      patientToday = home.patients?.today.patientSummary
      patientUpcoming = home.patients?.upcoming.map(\.patientSummary) ?? []
      statusMessage = "Synced \(Date().formatted(.dateTime.hour().minute().second()))"
    } catch {
      if days.isEmpty {
        days = ScheduleFixtures.week(containing: date)
      }
      statusMessage = "Live sync failed. Showing preview data. \(error.localizedDescription)"
    }
  }

  func requestOtp(email: String) async -> Bool {
    let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !normalizedEmail.isEmpty else { return false }

    authBusy = true
    authMessage = nil
    defer { authBusy = false }

    do {
      let message = try await client.requestOtp(email: normalizedEmail)
      authMessage = message.isEmpty ? "Code sent." : message
      return true
    } catch {
      authMessage = error.localizedDescription
      return false
    }
  }

  func verifyOtp(email: String, code: String) async {
    let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
    let normalizedCode = code.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !normalizedEmail.isEmpty, !normalizedCode.isEmpty else { return }

    authBusy = true
    authMessage = nil
    defer { authBusy = false }

    do {
      let token = try await client.verifyOtp(email: normalizedEmail, code: normalizedCode)
      try CALKeychain.saveSessionToken(token)
      sessionToken = token
      authMessage = nil
      await load(containing: Date(), scope: .week)
    } catch {
      authMessage = error.localizedDescription
    }
  }

  func logout() {
    CALKeychain.deleteSessionToken()
    sessionToken = nil
    days = []
    timeOffRequests = []
    currentSurgeon = nil
    surgeons = []
    patientToday = nil
    patientUpcoming = []
    statusMessage = nil
    authMessage = nil
    hasBootstrapped = true
  }

  func submitTimeOffRequest(startDate: Date, endDate: Date, reason: String, notes: String, segments: [RequestSegment]) async throws {
    guard let token = sessionToken, !token.isEmpty else {
      throw NativeCALError.missingSession
    }

    try await client.submitRequestOff(
      token: token,
      startDate: startDate,
      endDate: endDate,
      reason: reason,
      notes: notes,
      segments: segments
    )
    await load(containing: startDate, scope: .month)
  }

  func submitCallCoverage(assignment: ScheduleAssignment, coveringSurgeon: NativeSurgeon, selectedDate: Date, scope: ScheduleScope) async throws {
    guard let token = sessionToken, !token.isEmpty else {
      throw NativeCALError.missingSession
    }
    guard let rotationId = assignment.rotationId else {
      throw NativeCALError.requestRejected("This on-call row is preview data and cannot be updated.")
    }

    _ = try await client.submitCallCoverage(
      token: token,
      rotationId: rotationId,
      coveringSurgeonId: coveringSurgeon.id
    )
    await load(containing: selectedDate, scope: scope)
  }

  func setStatusMessage(_ message: String) {
    statusMessage = message
  }

  func eligibleCoveringSurgeons(for assignment: ScheduleAssignment) -> [NativeSurgeon] {
    guard !surgeons.isEmpty else { return [] }
    let originalId = assignment.originalSurgeonId ?? assignment.surgeonId
    let originalStaffType = originalId.flatMap { id in surgeons.first { $0.id == id }?.staffType }
    let fallbackStaffType = currentSurgeon?.staffType
    let targetStaffType = originalStaffType ?? fallbackStaffType
    return surgeons
      .filter { surgeon in
        guard let targetStaffType else { return true }
        return surgeon.staffType == targetStaffType
      }
      .sorted { lhs, rhs in
        (lhs.sortOrder ?? Int.max, lhs.initials) < (rhs.sortOrder ?? Int.max, rhs.initials)
      }
  }

  func day(for date: Date) -> ScheduleDay? {
    let key = dateKey(date)
    return days.first { $0.id == key }
  }

  func week(containing date: Date) -> [ScheduleDay] {
    let calendar = Calendar.current
    let interval = calendar.dateInterval(of: .weekOfYear, for: date)
    let start = interval?.start ?? calendar.startOfDay(for: date)

    return (0..<7).compactMap { offset in
      guard let dayDate = calendar.date(byAdding: .day, value: offset, to: start) else { return nil }
      return day(for: dayDate) ?? ScheduleFixtures.day(for: dayDate)
    }
  }

  func month(containing date: Date) -> [MonthCell] {
    let calendar = Calendar.current
    guard let monthInterval = calendar.dateInterval(of: .month, for: date) else { return [] }

    let firstOfMonth = monthInterval.start
    let leadingDays = calendar.component(.weekday, from: firstOfMonth) - 1
    let gridStart = calendar.date(byAdding: .day, value: -leadingDays, to: firstOfMonth) ?? firstOfMonth

    return (0..<42).compactMap { offset in
      guard let cellDate = calendar.date(byAdding: .day, value: offset, to: gridStart) else { return nil }
      let day = self.day(for: cellDate) ?? ScheduleFixtures.day(for: cellDate)
      return MonthCell(
        id: dateKey(cellDate),
        date: cellDate,
        isCurrentMonth: calendar.isDate(cellDate, equalTo: date, toGranularity: .month),
        isToday: calendar.isDateInToday(cellDate),
        assignments: day.assignments,
        callInitials: day.assignments.map(\.surgeon),
        offInitials: day.off,
        schedulePeriods: day.mySchedule.map(\.period)
      )
    }
  }
}
