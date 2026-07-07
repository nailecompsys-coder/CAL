import SwiftUI
import UIKit
import UserNotifications

@main
struct CALNativeApp: App {
  @UIApplicationDelegateAdaptor(CALAppDelegate.self) private var appDelegate

  var body: some Scene {
    WindowGroup {
      CALNativeRootView()
    }
  }
}

final class CALAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
  func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
    UNUserNotificationCenter.current().delegate = self
    return true
  }

  func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
    Task { @MainActor in
      NativePushRegistrar.shared.didRegister(deviceToken: deviceToken)
    }
  }

  func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
    Task { @MainActor in
      NativePushRegistrar.shared.didFailToRegister()
    }
  }

  func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification
  ) async -> UNNotificationPresentationOptions {
    [.banner, .sound, .badge]
  }
}
