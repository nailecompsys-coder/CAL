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
  private let loader = NativeScheduleLoader()
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
    guard let token = activeToken else {
      clearScheduleForMissingSession()
      return
    }
    await loadSnapshot {
      try await loader.load(token: token, containing: date, scope: scope)
    }
  }

  func loadLookahead(containing date: Date, daysAhead: Int = 30) async {
    guard let token = activeToken else {
      clearScheduleForMissingSession()
      return
    }
    await loadSnapshot {
      try await loader.loadLookahead(token: token, containing: date, daysAhead: daysAhead)
    }
  }

  private func loadSnapshot(_ operation: () async throws -> NativeScheduleSnapshot) async {
    loadState = .loading

    do {
      let snapshot = try await operation()
      apply(snapshot)
      loadState = .loaded
    } catch {
      loadState = .warning("Live sync failed. Showing last loaded schedule. \(error.localizedDescription)")
    }
  }

  private func apply(_ snapshot: NativeScheduleSnapshot) {
    currentSurgeon = snapshot.currentSurgeon
    surgeons = snapshot.surgeons
    days = snapshot.days
    timeOffRequests = snapshot.timeOffRequests
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

  private var activeToken: String? {
    guard let sessionToken, !sessionToken.isEmpty else { return nil }
    return sessionToken
  }

  private func clearScheduleForMissingSession() {
    days = []
    loadState = .idle
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
