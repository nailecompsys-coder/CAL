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

  func hasStoredToken() -> Bool {
    storedToken() != nil
  }

  func requestOtp(email: String, role: NativeSessionRole) async throws -> String {
    switch role {
    case .scheduler:
      if let schedulerMessage = try await client.requestSchedulerOtp(email: email) {
        return schedulerMessage
      }
      throw NSError(
        domain: "CALNative",
        code: 404,
        userInfo: [NSLocalizedDescriptionKey: "No scheduler account found for that email."]
      )
    case .surgeon:
      return try await client.requestOtp(email: email)
    }
  }

  func verifyOtp(email: String, code: String, role: NativeSessionRole) async throws -> NativeVerifiedSession {
    switch role {
    case .scheduler:
      let token = try await client.verifySchedulerOtp(email: email, code: code)
      try CALKeychain.saveSessionToken(token, role: .scheduler)
      return NativeVerifiedSession(token: token, role: .scheduler)
    case .surgeon:
      let token = try await client.verifyOtp(email: email, code: code)
      try CALKeychain.saveSessionToken(token, role: .surgeon)
      return NativeVerifiedSession(token: token, role: .surgeon)
    }
  }

  func clearToken() {
    CALKeychain.deleteSessionToken()
  }
}
