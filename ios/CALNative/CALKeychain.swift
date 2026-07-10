import Foundation
import Security

enum CALKeychain {
  private static let tokenKey = "cal_native_session_token"
  private static let roleKey = "cal_native_session_role"
  private static let primaryService = "app:no-auth"
  private static let fallbackService = "app"

  static func readSessionToken() -> String? {
    read(service: primaryService) ?? read(service: fallbackService)
  }

  static func readSessionRole() -> NativeSessionRole {
    guard let value = read(key: roleKey, service: primaryService),
          let role = NativeSessionRole(rawValue: value) else {
      return .surgeon
    }
    return role
  }

  static func saveSessionToken(_ token: String, role: NativeSessionRole = .surgeon) throws {
    try save(token, key: tokenKey, service: primaryService)
    try save(role.rawValue, key: roleKey, service: primaryService)
  }

  static func deleteSessionToken() {
    delete(key: tokenKey, service: primaryService)
    delete(key: tokenKey, service: fallbackService)
    delete(key: roleKey, service: primaryService)
    delete(key: roleKey, service: fallbackService)
  }

  private static func save(_ value: String, key: String, service: String) throws {
    let keyData = Data(key.utf8)
    let valueData = Data(value.utf8)
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

  private static func delete(key: String, service: String) {
    let keyData = Data(key.utf8)
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrGeneric as String: keyData,
      kSecAttrAccount as String: keyData
    ]
    SecItemDelete(query as CFDictionary)
  }

  private static func read(service: String) -> String? {
    read(key: tokenKey, service: service)
  }

  private static func read(key: String, service: String) -> String? {
    let keyData = Data(key.utf8)
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
