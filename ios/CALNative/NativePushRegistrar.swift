import Foundation
import UIKit
import UserNotifications

@MainActor
final class NativePushRegistrar {
  static let shared = NativePushRegistrar()

  private var pendingContinuation: CheckedContinuation<String?, Never>?

  private init() {}

  func requestToken() async -> String? {
    let center = UNUserNotificationCenter.current()
    do {
      let granted = try await center.requestAuthorization(options: [.alert, .badge, .sound])
      guard granted else { return nil }
    } catch {
      return nil
    }

    return await withCheckedContinuation { continuation in
      pendingContinuation = continuation
      UIApplication.shared.registerForRemoteNotifications()
    }
  }

  func didRegister(deviceToken: Data) {
    let token = deviceToken.map { String(format: "%02x", $0) }.joined()
    pendingContinuation?.resume(returning: token)
    pendingContinuation = nil
  }

  func didFailToRegister() {
    pendingContinuation?.resume(returning: nil)
    pendingContinuation = nil
  }
}
