import Foundation
import Security

enum CALKeychain {
  private static let tokenKey = "cal_native_session_token"
  private static let roleKey = "cal_native_session_role"
  private static let surgeonTokenKey = "cal_native_surgeon_token"
  private static let schedulerTokenKey = "cal_native_scheduler_token"
  private static let rolesKey = "cal_native_available_roles"
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

  static func readSurgeonToken() -> String? {
    read(key: surgeonTokenKey, service: primaryService)
  }

  static func readSchedulerToken() -> String? {
    read(key: schedulerTokenKey, service: primaryService)
  }

  static func readAvailableRoles() -> [NativeSessionRole] {
    guard let raw = read(key: rolesKey, service: primaryService), !raw.isEmpty else {
      return [readSessionRole()]
    }
    let roles = raw.split(separator: ",").compactMap { NativeSessionRole(rawValue: String($0)) }
    return roles.isEmpty ? [readSessionRole()] : roles
  }

  static func saveSessionToken(_ token: String, role: NativeSessionRole = .surgeon) throws {
    try save(token, key: tokenKey, service: primaryService)
    try save(role.rawValue, key: roleKey, service: primaryService)
  }

  static func saveDualSession(
    activeToken: String,
    activeRole: NativeSessionRole,
    availableRoles: [NativeSessionRole],
    surgeonToken: String?,
    schedulerToken: String?
  ) throws {
    try saveSessionToken(activeToken, role: activeRole)
    let rolesValue = availableRoles.map(\.rawValue).joined(separator: ",")
    try save(rolesValue, key: rolesKey, service: primaryService)
    if let surgeonToken, !surgeonToken.isEmpty {
      try save(surgeonToken, key: surgeonTokenKey, service: primaryService)
    } else {
      delete(key: surgeonTokenKey, service: primaryService)
    }
    if let schedulerToken, !schedulerToken.isEmpty {
      try save(schedulerToken, key: schedulerTokenKey, service: primaryService)
    } else {
      delete(key: schedulerTokenKey, service: primaryService)
    }
  }

  static func deleteSessionToken() {
    delete(key: tokenKey, service: primaryService)
    delete(key: tokenKey, service: fallbackService)
    delete(key: roleKey, service: primaryService)
    delete(key: roleKey, service: fallbackService)
    delete(key: surgeonTokenKey, service: primaryService)
    delete(key: schedulerTokenKey, service: primaryService)
    delete(key: rolesKey, service: primaryService)
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
