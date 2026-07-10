import SwiftUI
import UIKit
import UserNotifications

@main
struct CALNativeApp: App {
  @UIApplicationDelegateAdaptor(CALAppDelegate.self) private var appDelegate

  var body: some Scene {
    WindowGroup {
      CALNativeRootView()
        #if targetEnvironment(macCatalyst)
        .frame(minWidth: 980, minHeight: 700)
        #endif
    }
  }
}

final class CALAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
  func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
    UNUserNotificationCenter.current().delegate = self
    return true
  }

  func applicationDidBecomeActive(_ application: UIApplication) {
    #if targetEnvironment(macCatalyst)
    configureMacCatalystWindow()
    #endif
  }

  #if targetEnvironment(macCatalyst)
  private func configureMacCatalystWindow() {
    for scene in UIApplication.shared.connectedScenes {
      guard let windowScene = scene as? UIWindowScene else { continue }
      windowScene.titlebar?.titleVisibility = .visible
      windowScene.sizeRestrictions?.minimumSize = CGSize(width: 980, height: 700)
    }
  }
  #endif

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
