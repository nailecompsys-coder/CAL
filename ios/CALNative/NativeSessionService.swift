import Foundation

struct NativeSessionService {
  private let client: NativeCALClient

  init(client: NativeCALClient = NativeCALClient()) {
    self.client = client
  }

  func storedToken() -> String? {
    CALKeychain.readSessionToken()
  }

  func requestOtp(email: String) async throws -> String {
    try await client.requestOtp(email: email)
  }

  func verifyOtp(email: String, code: String) async throws -> String {
    let token = try await client.verifyOtp(email: email, code: code)
    try CALKeychain.saveSessionToken(token)
    return token
  }

  func clearToken() {
    CALKeychain.deleteSessionToken()
  }
}
