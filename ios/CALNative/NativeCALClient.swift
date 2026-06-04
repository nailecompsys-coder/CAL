import Foundation

struct NativeCALClient {
  private let baseURL = URL(string: "https://cal.midfloridasurgical.com")!

  func requestOtp(email: String) async throws -> String {
    var request = URLRequest(url: baseURL.appendingPathComponent("/api/surgeon/otp/request"))
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONEncoder().encode(OtpRequestPayload(email: email))

    let response = try await perform(request)
    let result = try JSONDecoder().decode(OtpRequestResponse.self, from: response)
    return result.message ?? ""
  }

  func verifyOtp(email: String, code: String) async throws -> String {
    var request = URLRequest(url: baseURL.appendingPathComponent("/api/surgeon/otp/verify"))
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONEncoder().encode(OtpVerifyPayload(email: email, code: code))

    let response = try await perform(request)
    let result = try JSONDecoder().decode(OtpVerifyResponse.self, from: response)
    return result.token
  }

  func fetchHome(token: String, start: Date, end: Date) async throws -> NativeHomeResponse {
    var components = URLComponents(url: baseURL.appendingPathComponent("/api/native/home"), resolvingAgainstBaseURL: false)!
    components.queryItems = [
      URLQueryItem(name: "start", value: isoDate(start)),
      URLQueryItem(name: "end", value: isoDate(end))
    ]

    guard let url = components.url else {
      throw NativeCALError.invalidURL
    }

    var request = URLRequest(url: url)
    request.httpMethod = "GET"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.setValue(token, forHTTPHeaderField: "X-CAL-Device-Token")

    let data = try await perform(request)
    return try JSONDecoder().decode(NativeHomeResponse.self, from: data)
  }

  func submitRequestOff(token: String, startDate: Date, endDate: Date, reason: String, notes: String, segments: [RequestSegment]) async throws {
    let url = baseURL.appendingPathComponent("/api/native/request-off")
    let normalizedSegments = segments.isEmpty ? [RequestSegment(date: startDate, isFullDay: true, start: "07:00", end: "17:00")] : segments
    let firstPartial = normalizedSegments.first { !$0.isFullDay }
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.setValue(token, forHTTPHeaderField: "X-CAL-Device-Token")
    request.httpBody = try JSONEncoder().encode(TimeOffSubmitPayload(
      startDate: isoDate(startDate),
      endDate: isoDate(endDate),
      reason: reason,
      notes: notes,
      isFullDay: normalizedSegments.allSatisfy(\.isFullDay),
      start: firstPartial?.start,
      end: firstPartial?.end,
      segments: normalizedSegments.map { segment in
        TimeOffSubmitSegment(
          date: isoDate(segment.date),
          isFullDay: segment.isFullDay,
          start: segment.start,
          end: segment.end
        )
      }
    ))

    let data = try await perform(request)
    let result = try JSONDecoder().decode(NativeRequestOffResponse.self, from: data)
    if !result.ok {
      throw NativeCALError.requestRejected(result.warnings.joined(separator: " "))
    }
  }

  func submitCallCoverage(token: String, rotationId: Int, coveringSurgeonId: Int, notes: String = "") async throws -> NativeCallAssignmentResponse {
    let url = baseURL.appendingPathComponent("/api/native/call-coverage")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.setValue(token, forHTTPHeaderField: "X-CAL-Device-Token")
    request.httpBody = try JSONEncoder().encode(NativeCallCoveragePayload(
      rotationId: rotationId,
      coveringSurgeonId: coveringSurgeonId,
      notes: notes
    ))

    let data = try await perform(request)
    let result = try JSONDecoder().decode(NativeCallCoverageResponse.self, from: data)
    return result.assignment
  }

  private func perform(_ request: URLRequest) async throws -> Data {
    let (data, response) = try await URLSession.shared.data(for: request)
    guard let http = response as? HTTPURLResponse else {
      throw NativeCALError.invalidResponse
    }
    guard (200..<300).contains(http.statusCode) else {
      let body = String(data: data, encoding: .utf8) ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
      throw NativeCALError.http(http.statusCode, body)
    }
    return data
  }

  private func isoDate(_ date: Date) -> String {
    Self.dateFormatter.string(from: date)
  }

  private static let dateFormatter: DateFormatter = {
    let formatter = DateFormatter()
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.dateFormat = "yyyy-MM-dd"
    return formatter
  }()
}

enum NativeCALError: LocalizedError {
  case invalidURL
  case invalidResponse
  case http(Int, String)
  case keychain(OSStatus)
  case missingSession
  case requestRejected(String)

  var errorDescription: String? {
    switch self {
    case .invalidURL:
      return "Invalid CAL API URL."
    case .invalidResponse:
      return "Invalid CAL API response."
    case .http(let status, let body):
      return "HTTP \(status): \(body)"
    case .keychain(let status):
      return "Could not save sign-in token. Keychain status \(status)."
    case .missingSession:
      return "Sign in is needed before submitting."
    case .requestRejected(let message):
      return message.isEmpty ? "Request was not submitted." : message
    }
  }
}
