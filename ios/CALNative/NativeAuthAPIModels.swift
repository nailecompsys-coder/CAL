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
}

struct OtpVerifyResponse: Decodable {
  let token: String
}
