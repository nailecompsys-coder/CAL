import SwiftUI
import UIKit

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
  @Published private(set) var patientAppointments: [PatientAppointment] = []
  @Published private(set) var currentSurgeon: NativeSurgeon?
  @Published private(set) var surgeons: [NativeSurgeon] = []
  @Published private(set) var alerts = NativeAlertSummary(unreadCount: 0, recent: [])
  @Published private(set) var loadState: NativeLoadState = .idle
  @Published private(set) var sessionToken: String?
  @Published private(set) var hasBootstrapped = false
  @Published private(set) var canUnlockStoredSession = false
  @Published private(set) var biometricBusy = false
  @Published private(set) var authBusy = false
  @Published private(set) var authMessage: String?

  private let client = NativeCALClient()
  private let actions = NativeScheduleActions()
  private let loader = NativeScheduleLoader()
  private let session = NativeSessionService()
  private let biometric = NativeBiometricService()
  private let pushRegistrar = NativePushRegistrar.shared
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
    hasBootstrapped = true
    if await unlockStoredSessionIfPossible() {
      await load(containing: date, scope: scope)
    }
  }

  func bootstrapLookahead(containing date: Date, daysAhead: Int = 30) async {
    hasBootstrapped = true
    if await unlockStoredSessionIfPossible() {
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

  func loadPatientSchedule(containing date: Date, daysAhead: Int = 6) async {
    guard let token = activeToken else {
      clearScheduleForMissingSession()
      return
    }

    loadState = .loading
    let calendar = Calendar.current
    let start = calendar.startOfDay(for: date)
    let end = calendar.date(byAdding: .day, value: daysAhead, to: start) ?? start

    do {
      let response = try await client.fetchPatientSchedule(token: token, start: start, end: end)
      patientAppointments = response.appointments.map(\.patientAppointment)
      if let warning = response.warning, !warning.isEmpty {
        loadState = .warning(warning)
      } else {
        loadState = .loaded
      }
    } catch let error as NativeCALError where error.isAuthenticationFailure {
      expireSession()
    } catch {
      loadState = .warning("Aprima schedule failed. \(error.localizedDescription)")
    }
  }

  private func loadSnapshot(_ operation: () async throws -> NativeScheduleSnapshot) async {
    loadState = .loading

    do {
      let snapshot = try await operation()
      apply(snapshot)
      loadState = .loaded
    } catch let error as NativeCALError where error.isAuthenticationFailure {
      expireSession()
    } catch {
      loadState = .warning("Live sync failed. Showing last loaded schedule. \(error.localizedDescription)")
    }
  }

  private func apply(_ snapshot: NativeScheduleSnapshot) {
    currentSurgeon = snapshot.currentSurgeon
    surgeons = snapshot.surgeons
    days = snapshot.days
    timeOffRequests = snapshot.timeOffRequests
    alerts = snapshot.alerts
    Task {
      await registerForPushIfPossible()
    }
  }

  func requestOtp(email: String) async -> Bool {
    let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !normalizedEmail.isEmpty else { return false }

    authBusy = true
    authMessage = nil
    defer { authBusy = false }

    do {
      _ = try await session.requestOtp(email: normalizedEmail)
      authMessage = "Check your email for the CAL access code."
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
      canUnlockStoredSession = false
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
    patientAppointments = []
    alerts = NativeAlertSummary(unreadCount: 0, recent: [])
    currentSurgeon = nil
    surgeons = []
    loadState = .idle
    authMessage = nil
    hasBootstrapped = true
    canUnlockStoredSession = false
  }

  private func expireSession() {
    session.clearToken()
    sessionToken = nil
    days = []
    timeOffRequests = []
    patientAppointments = []
    alerts = NativeAlertSummary(unreadCount: 0, recent: [])
    currentSurgeon = nil
    surgeons = []
    loadState = .idle
    authMessage = "For security, please sign in again."
    hasBootstrapped = true
    canUnlockStoredSession = session.hasStoredToken()
  }

  func submitTimeOffRequest(startDate: Date, endDate: Date, reason: String, notes: String, segments: [RequestSegment]) async throws -> [String] {
    guard let token = sessionToken, !token.isEmpty else {
      throw NativeCALError.missingSession
    }

    let warnings = try await actions.submitTimeOffRequest(
      token: token,
      startDate: startDate,
      endDate: endDate,
      reason: reason,
      notes: notes,
      segments: segments
    )
    await load(containing: startDate, scope: .month)
    return warnings
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

  func unlockSavedSession() async {
    _ = await unlockStoredSessionIfPossible(forcePrompt: true)
    if sessionToken != nil {
      await loadLookahead(containing: Date(), daysAhead: 30)
    }
  }

  func markAlertsRead() async {
    guard let token = activeToken else { return }
    do {
      try await client.markAlertsRead(token: token)
      alerts = NativeAlertSummary(
        unreadCount: 0,
        recent: alerts.recent.map { NativeScheduleAlert(
          id: $0.id,
          title: $0.title,
          body: $0.body,
          kind: $0.kind,
          isRead: true,
          createdAt: $0.createdAt
        ) }
      )
      await loadLookahead(containing: Date(), daysAhead: 30)
    } catch {
      authMessage = error.localizedDescription
    }
  }

  private func unlockStoredSessionIfPossible(forcePrompt: Bool = false) async -> Bool {
    guard sessionToken == nil, session.hasStoredToken() else {
      return sessionToken != nil
    }
    canUnlockStoredSession = biometric.canUnlockSavedSession()
    guard canUnlockStoredSession || forcePrompt else {
      authMessage = "Use your 6-digit code to sign in on this device."
      return false
    }
    biometricBusy = true
    defer { biometricBusy = false }
    do {
      try await biometric.unlockSavedSession()
      sessionToken = session.storedToken()
      canUnlockStoredSession = false
      authMessage = nil
      return sessionToken != nil
    } catch {
      authMessage = "Face ID was not completed. Use your 6-digit code to sign in."
      canUnlockStoredSession = true
      return false
    }
  }

  private func registerForPushIfPossible() async {
    guard let token = activeToken else { return }
    guard let pushToken = await pushRegistrar.requestToken(), !pushToken.isEmpty else { return }
    let deviceName = UIDevice.current.localizedModel
    try? await client.registerPushToken(
      token: token,
      pushToken: pushToken,
      platform: "ios",
      provider: "apns",
      deviceName: deviceName
    )
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
