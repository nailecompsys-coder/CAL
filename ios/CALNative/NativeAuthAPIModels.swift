import Foundation

struct OtpRequestPayload: Encodable {
  let email: String
}

struct OtpVerifyPayload: Encodable {
  let email: String
  let code: String
}

struct OtpRequestResponse: Decodable {
  let ok: Bool?
  let message: String?
  let sent: Bool?
  let scheduler: Bool?
  let roles: [String]?
  let devCode: String?
}

struct OtpVerifyResponse: Decodable {
  let token: String
}

struct NativeUnifiedOtpVerifyResponse: Decodable {
  let token: String
  let role: String
  let roles: [String]
  let tokens: NativeUnifiedOtpTokens
}

struct NativeUnifiedOtpTokens: Decodable {
  let surgeon: String?
  let scheduler: String?
}

struct SchedulerOtpVerifyResponse: Decodable {
  let token: String
  let identity: SchedulerIdentityResponse
}

struct SchedulerIdentityResponse: Decodable {
  let id: Int
  let role: String
  let name: String
  let email: String
}
