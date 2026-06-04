import Foundation
import Security

enum CALKeychain {
  private static let tokenKey = "cal_native_session_token"
  private static let primaryService = "app:no-auth"
  private static let fallbackService = "app"

  static func readSessionToken() -> String? {
    read(service: primaryService) ?? read(service: fallbackService)
  }

  static func saveSessionToken(_ token: String) throws {
    try save(token, service: primaryService)
  }

  static func deleteSessionToken() {
    delete(service: primaryService)
    delete(service: fallbackService)
  }

  private static func save(_ token: String, service: String) throws {
    let keyData = Data(tokenKey.utf8)
    let valueData = Data(token.utf8)
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrGeneric as String: keyData,
      kSecAttrAccount as String: keyData
    ]
    let attributes: [String: Any] = [
      kSecValueData as String: valueData
    ]

    let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
    if updateStatus == errSecSuccess {
      return
    }
    guard updateStatus == errSecItemNotFound else {
      throw NativeCALError.keychain(updateStatus)
    }

    var addQuery = query
    addQuery[kSecValueData as String] = valueData
    addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
    let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
    guard addStatus == errSecSuccess else {
      throw NativeCALError.keychain(addStatus)
    }
  }

  private static func delete(service: String) {
    let keyData = Data(tokenKey.utf8)
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrGeneric as String: keyData,
      kSecAttrAccount as String: keyData
    ]
    SecItemDelete(query as CFDictionary)
  }

  private static func read(service: String) -> String? {
    let keyData = Data(tokenKey.utf8)
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrGeneric as String: keyData,
      kSecAttrAccount as String: keyData,
      kSecMatchLimit as String: kSecMatchLimitOne,
      kSecReturnData as String: kCFBooleanTrue as Any
    ]

    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    guard status == errSecSuccess, let data = item as? Data else {
      return nil
    }
    return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
  }
}
