import Foundation
import LocalAuthentication

struct NativeBiometricService {
  func canUnlockSavedSession() -> Bool {
    let context = LAContext()
    var error: NSError?
    return context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
  }

  func unlockSavedSession() async throws {
    let context = LAContext()
    context.localizedCancelTitle = "Use OTP"
    try await context.evaluatePolicy(
      .deviceOwnerAuthenticationWithBiometrics,
      localizedReason: "Unlock CAL with Face ID."
    )
  }
}
