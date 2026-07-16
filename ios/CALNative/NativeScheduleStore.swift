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
  @Published private(set) var sessionRole: NativeSessionRole = .surgeon
  @Published private(set) var schedulerBlocks: [NativeSchedulerBlock] = []
  @Published private(set) var schedulerChanges: [NativeSchedulerChange] = []
  @Published private(set) var selectedSchedulerDetail: NativeSchedulerBlockDetailResponse?
  @Published private(set) var hasBootstrapped = false
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
      if sessionRole == .scheduler {
        await loadScheduler(containing: date)
      } else {
        await load(containing: date, scope: scope)
      }
    }
  }

  func bootstrapLookahead(containing date: Date, daysAhead: Int = 30) async {
    hasBootstrapped = true
    #if DEBUG
    if let email = Self.debugLoginEmail() {
      session.clearToken()
      sessionToken = nil
      sessionRole = .surgeon
      await verifyOtp(email: email, code: "654321", role: .surgeon)
      return
    }
    #endif
    if await unlockStoredSessionIfPossible() {
      if sessionRole == .scheduler {
        await loadScheduler(containing: date)
      } else {
        await loadLookahead(containing: date, daysAhead: daysAhead)
      }
    }
  }

  #if DEBUG
  private static func debugLoginEmail() -> String? {
    guard let arg = CommandLine.arguments.first(where: { $0.hasPrefix("--cal-login=") }) else {
      return nil
    }
    let email = String(arg.dropFirst("--cal-login=".count))
      .trimmingCharacters(in: .whitespacesAndNewlines)
    return email.isEmpty ? nil : email
  }
  #endif

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

  func requestOtp(email: String, role: NativeSessionRole = .surgeon) async -> Bool {
    let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !normalizedEmail.isEmpty else { return false }

    authBusy = true
    authMessage = nil
    defer { authBusy = false }

    do {
      let message = try await session.requestOtp(email: normalizedEmail, role: role)
      authMessage = message.isEmpty
        ? (role == .scheduler
          ? "Check your email for the CAL scheduler code."
          : "Check your email for the CAL access code.")
        : message
      return true
    } catch {
      authMessage = error.localizedDescription
      return false
    }
  }

  func verifyOtp(email: String, code: String, role: NativeSessionRole = .surgeon) async {
    let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
    let normalizedCode = code.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !normalizedEmail.isEmpty, !normalizedCode.isEmpty else { return }

    authBusy = true
    authMessage = nil
    defer { authBusy = false }

    do {
      let verified = try await session.verifyOtp(email: normalizedEmail, code: normalizedCode, role: role)
      sessionToken = verified.token
      sessionRole = verified.role
      authMessage = nil
      if verified.role == .scheduler {
        await loadScheduler(containing: Date())
      } else {
        await load(containing: Date(), scope: .week)
      }
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
    schedulerBlocks = []
    schedulerChanges = []
    selectedSchedulerDetail = nil
    sessionRole = .surgeon
    alerts = NativeAlertSummary(unreadCount: 0, recent: [])
    currentSurgeon = nil
    surgeons = []
    loadState = .idle
    authMessage = nil
    hasBootstrapped = true
  }

  private func expireSession() {
    session.clearToken()
    sessionToken = nil
    days = []
    timeOffRequests = []
    patientAppointments = []
    schedulerBlocks = []
    schedulerChanges = []
    selectedSchedulerDetail = nil
    sessionRole = .surgeon
    alerts = NativeAlertSummary(unreadCount: 0, recent: [])
    currentSurgeon = nil
    surgeons = []
    loadState = .idle
    authMessage = "For security, please sign in again."
    hasBootstrapped = true
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

  func cancelCallCoverage(assignment: ScheduleAssignment, selectedDate: Date, scope: ScheduleScope) async throws {
    guard let token = sessionToken, !token.isEmpty else {
      throw NativeCALError.missingSession
    }

    try await actions.cancelCallCoverage(
      token: token,
      assignment: assignment
    )
    await load(containing: selectedDate, scope: scope)
  }

  func setWarningMessage(_ message: String) {
    loadState = .warning(message)
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

  private func unlockStoredSessionIfPossible() async -> Bool {
    guard sessionToken == nil, session.hasStoredToken() else {
      return sessionToken != nil
    }
    guard biometric.canUnlockSavedSession() else {
      return false
    }
    do {
      try await biometric.unlockSavedSession()
      sessionToken = session.storedToken()
      sessionRole = session.storedRole()
      authMessage = nil
      return sessionToken != nil
    } catch {
      authMessage = nil
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

  func loadScheduler(containing date: Date) async {
    guard let token = activeToken else {
      clearScheduleForMissingSession()
      return
    }
    loadState = .loading
    let calendar = Calendar.current
    let start = calendar.startOfDay(for: date)
    let end = calendar.date(byAdding: .day, value: 56, to: start) ?? start
    do {
      let response = try await client.fetchSchedulerHome(token: token, start: start, end: end)
      schedulerBlocks = response.blocks
      schedulerChanges = response.changes
      loadState = .loaded
    } catch let error as NativeCALError where error.isAuthenticationFailure {
      expireSession()
    } catch {
      loadState = .warning("Scheduler sync failed. \(error.localizedDescription)")
    }
  }

  func loadSchedulerBlock(_ block: NativeSchedulerBlock) async {
    guard let token = activeToken else { return }
    do {
      selectedSchedulerDetail = try await client.fetchSchedulerBlock(token: token, blockId: block.id)
    } catch {
      loadState = .warning(error.localizedDescription)
    }
  }

  func assignSchedulerBlock(blockId: Int, surgeonId: Int, startTime: String, caseCount: Int, note: String) async throws -> [String] {
    guard let token = activeToken else {
      throw NativeCALError.missingSession
    }
    let response = try await client.assignSchedulerBlock(
      token: token,
      blockId: blockId,
      surgeonId: surgeonId,
      startTime: startTime,
      caseCount: caseCount,
      note: note
    )
    await refreshSchedulerAfterMutation(blockId: blockId, dateString: response.block.date)
    return response.warnings
  }

  func updateSchedulerAssignment(
    blockId: Int,
    assignmentId: Int,
    surgeonId: Int,
    startTime: String,
    caseCount: Int,
    note: String
  ) async throws -> [String] {
    guard let token = activeToken else {
      throw NativeCALError.missingSession
    }
    let response = try await client.updateSchedulerAssignment(
      token: token,
      blockId: blockId,
      assignmentId: assignmentId,
      surgeonId: surgeonId,
      startTime: startTime,
      caseCount: caseCount,
      note: note
    )
    await refreshSchedulerAfterMutation(blockId: blockId, dateString: response.block.date)
    return response.warnings
  }

  func removeSchedulerAssignment(blockId: Int, assignmentId: Int) async throws {
    guard let token = activeToken else {
      throw NativeCALError.missingSession
    }
    let response = try await client.removeSchedulerAssignment(
      token: token,
      blockId: blockId,
      assignmentId: assignmentId
    )
    await refreshSchedulerAfterMutation(blockId: blockId, dateString: response.block.date)
  }

  func clearSchedulerBlock(blockId: Int) async throws {
    guard let token = activeToken else {
      throw NativeCALError.missingSession
    }
    let response = try await client.clearSchedulerBlock(token: token, blockId: blockId)
    selectedSchedulerDetail = nil
    await loadScheduler(containing: NativeDayResponse.dateFormatter.date(from: response.block.date) ?? Date())
  }

  private func refreshSchedulerAfterMutation(blockId: Int, dateString: String) async {
    guard let token = activeToken else { return }
    do {
      selectedSchedulerDetail = try await client.fetchSchedulerBlock(token: token, blockId: blockId)
    } catch {
      selectedSchedulerDetail = nil
      setWarningMessage(error.localizedDescription)
    }
    await loadScheduler(containing: NativeDayResponse.dateFormatter.date(from: dateString) ?? Date())
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
