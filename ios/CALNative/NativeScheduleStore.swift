import SwiftUI

enum NativeLoadState: Equatable {
  case idle
  case loading
  case loaded
  case warning(String)
}

@MainActor
final class NativeScheduleStore: ObservableObject {
  @Published private(set) var days: [ScheduleDay] = []
  @Published private(set) var timeOffRequests: [TimeOffRequest] = []
  @Published private(set) var currentSurgeon: NativeSurgeon?
  @Published private(set) var surgeons: [NativeSurgeon] = []
  @Published private(set) var loadState: NativeLoadState = .idle
  @Published private(set) var sessionToken: String?
  @Published private(set) var hasBootstrapped = false
  @Published private(set) var authBusy = false
  @Published private(set) var authMessage: String?

  private let client = NativeCALClient()
  private let actions = NativeScheduleActions()
  private let session = NativeSessionService()
  private var projection: NativeScheduleProjection {
    NativeScheduleProjection(days: days)
  }

  var isLoading: Bool {
    loadState == .loading
  }

  var warningMessage: String? {
    if case let .warning(message) = loadState {
      return message
    }
    return nil
  }

  func bootstrap(containing date: Date, scope: ScheduleScope) async {
    restoreStoredTokenIfNeeded()
    hasBootstrapped = true
    if sessionToken != nil {
      await load(containing: date, scope: scope)
    }
  }

  func bootstrapLookahead(containing date: Date, daysAhead: Int = 30) async {
    restoreStoredTokenIfNeeded()
    hasBootstrapped = true
    if sessionToken != nil {
      await loadLookahead(containing: date, daysAhead: daysAhead)
    }
  }

  func load(containing date: Date, scope: ScheduleScope) async {
    let range = DateRange(containing: date, scope: scope)
    await loadRange(start: range.start, end: range.end, fallbackDate: date)
  }

  func loadLookahead(containing date: Date, daysAhead: Int = 30) async {
    let calendar = Calendar.current
    let start = calendar.startOfDay(for: date)
    let end = calendar.date(byAdding: .day, value: daysAhead, to: start) ?? start
    await loadRange(start: start, end: end, fallbackDate: date)
  }

  private func loadRange(start: Date, end: Date, fallbackDate: Date) async {
    guard let token = sessionToken, !token.isEmpty else {
      days = ScheduleFixtures.week(containing: fallbackDate)
      loadState = .idle
      return
    }

    loadState = .loading

    do {
      let home = try await client.fetchHome(token: token, start: start, end: end)
      apply(home)
      loadState = .loaded
    } catch {
      if days.isEmpty {
        days = ScheduleFixtures.week(containing: fallbackDate)
      }
      loadState = .warning("Live sync failed. Showing preview data. \(error.localizedDescription)")
    }
  }

  private func apply(_ home: NativeHomeResponse) {
    currentSurgeon = home.surgeon
    surgeons = home.surgeons ?? []
    days = home.days.map { $0.scheduleDay }
    timeOffRequests = home.requests.map(\.timeOffRequest)
  }

  func requestOtp(email: String) async -> Bool {
    let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !normalizedEmail.isEmpty else { return false }

    authBusy = true
    authMessage = nil
    defer { authBusy = false }

    do {
      let message = try await session.requestOtp(email: normalizedEmail)
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
      let token = try await session.verifyOtp(email: normalizedEmail, code: normalizedCode)
      sessionToken = token
      authMessage = nil
      await load(containing: Date(), scope: .week)
    } catch {
      authMessage = error.localizedDescription
    }
  }

  func logout() {
    session.clearToken()
    sessionToken = nil
    days = []
    timeOffRequests = []
    currentSurgeon = nil
    surgeons = []
    loadState = .idle
    authMessage = nil
    hasBootstrapped = true
  }

  func submitTimeOffRequest(startDate: Date, endDate: Date, reason: String, notes: String, segments: [RequestSegment]) async throws {
    guard let token = sessionToken, !token.isEmpty else {
      throw NativeCALError.missingSession
    }

    try await actions.submitTimeOffRequest(
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

    try await actions.submitCallCoverage(
      token: token,
      assignment: assignment,
      coveringSurgeon: coveringSurgeon
    )
    await load(containing: selectedDate, scope: scope)
  }

  func setWarningMessage(_ message: String) {
    loadState = .warning(message)
  }

  private func restoreStoredTokenIfNeeded() {
    if sessionToken == nil {
      sessionToken = session.storedToken()
    }
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
    projection.day(for: date)
  }

  func week(containing date: Date) -> [ScheduleDay] {
    projection.week(containing: date)
  }

  func month(containing date: Date) -> [MonthCell] {
    projection.month(containing: date)
  }
}
