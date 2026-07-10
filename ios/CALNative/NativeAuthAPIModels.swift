import Foundation

struct OtpRequestPayload: Encodable {
  let email: String
}

struct OtpVerifyPayload: Encodable {
  let email: String
  let code: String
}

struct OtpRequestResponse: Decodable {
  let message: String?
  let sent: Bool?
  let scheduler: Bool?
  let devCode: String?
}

struct OtpVerifyResponse: Decodable {
  let token: String
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
