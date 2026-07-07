import Foundation
import LocalAuthentication

struct NativeBiometricService {
  func canUnlockSavedSession() -> Bool {
    let context = LAContext()
    var error: NSError?
    return context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error)
  }

  func unlockSavedSession() async throws {
    let context = LAContext()
    context.localizedCancelTitle = "Use Code"
    try await context.evaluatePolicy(
      .deviceOwnerAuthentication,
      localizedReason: "Unlock CAL with Face ID or your device passcode."
    )
  }
}
