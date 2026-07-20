import Foundation

struct NativeSessionService {
  private let client: NativeCALClient

  init(client: NativeCALClient = NativeCALClient()) {
    self.client = client
    if CommandLine.arguments.contains("--reset-cal-session") {
      CALKeychain.deleteSessionToken()
    }
  }

  func storedToken() -> String? {
    CALKeychain.readSessionToken()
  }

  func storedRole() -> NativeSessionRole {
    CALKeychain.readSessionRole()
  }

  func storedAvailableRoles() -> [NativeSessionRole] {
    CALKeychain.readAvailableRoles()
  }

  func storedSurgeonToken() -> String? {
    CALKeychain.readSurgeonToken()
  }

  func storedSchedulerToken() -> String? {
    CALKeychain.readSchedulerToken()
  }

  func hasStoredToken() -> Bool {
    storedToken() != nil
  }

  func requestOtp(email: String) async throws -> String {
    try await client.requestUnifiedOtp(email: email)
  }

  func verifyOtp(email: String, code: String) async throws -> NativeVerifiedSession {
    let verified = try await client.verifyUnifiedOtp(email: email, code: code)
    let availableRoles = verified.roles.compactMap { NativeSessionRole(rawValue: $0) }
    let activeRole = NativeSessionRole(rawValue: verified.role) ?? availableRoles.first ?? .surgeon
    let surgeonToken = verified.tokens.surgeon
    let schedulerToken = verified.tokens.scheduler
    let activeToken: String
    switch activeRole {
    case .surgeon:
      activeToken = surgeonToken ?? verified.token
    case .scheduler:
      activeToken = schedulerToken ?? verified.token
    }

    try CALKeychain.saveDualSession(
      activeToken: activeToken,
      activeRole: activeRole,
      availableRoles: availableRoles.isEmpty ? [activeRole] : availableRoles,
      surgeonToken: surgeonToken,
      schedulerToken: schedulerToken
    )
    return NativeVerifiedSession(
      token: activeToken,
      role: activeRole,
      availableRoles: availableRoles.isEmpty ? [activeRole] : availableRoles,
      surgeonToken: surgeonToken,
      schedulerToken: schedulerToken
    )
  }

  func switchRole(_ role: NativeSessionRole) throws -> String {
    let token: String?
    switch role {
    case .surgeon:
      token = CALKeychain.readSurgeonToken()
    case .scheduler:
      token = CALKeychain.readSchedulerToken()
    }
    guard let token, !token.isEmpty else {
      throw NSError(
        domain: "CALNative",
        code: 403,
        userInfo: [NSLocalizedDescriptionKey: "That mode is not available for this login."]
      )
    }
    let roles = CALKeychain.readAvailableRoles()
    try CALKeychain.saveDualSession(
      activeToken: token,
      activeRole: role,
      availableRoles: roles,
      surgeonToken: CALKeychain.readSurgeonToken(),
      schedulerToken: CALKeychain.readSchedulerToken()
    )
    return token
  }

  func clearToken() {
    CALKeychain.deleteSessionToken()
  }
}
