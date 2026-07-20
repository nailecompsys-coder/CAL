import Foundation

struct NativeCALClient {
  #if DEBUG
  private let baseURL = URL(string: "http://127.0.0.1:3005")!
  #else
  private let baseURL = URL(string: "https://cal.midfloridasurgical.com")!
  #endif

  func requestOtp(email: String) async throws -> String {
    var request = URLRequest(url: baseURL.appendingPathComponent("/api/surgeon/otp/request"))
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONEncoder().encode(OtpRequestPayload(email: email))

    let response = try await perform(request)
    let result = try JSONDecoder().decode(OtpRequestResponse.self, from: response)
    return result.message ?? ""
  }

  func requestSchedulerOtp(email: String) async throws -> String? {
    var request = URLRequest(url: baseURL.appendingPathComponent("/api/native/scheduler/otp/request"))
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONEncoder().encode(OtpRequestPayload(email: email))

    let response = try await perform(request)
    let result = try JSONDecoder().decode(OtpRequestResponse.self, from: response)
    guard result.scheduler == true else { return nil }
    if let devCode = result.devCode, !devCode.isEmpty {
      return "Local scheduler code: \(devCode)"
    }
    return result.message ?? "Check your email or iPhone for the CAL scheduler code."
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

  func verifySchedulerOtp(email: String, code: String) async throws -> String {
    var request = URLRequest(url: baseURL.appendingPathComponent("/api/native/scheduler/otp/verify"))
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONEncoder().encode(OtpVerifyPayload(email: email, code: code))

    let response = try await perform(request)
    let result = try JSONDecoder().decode(SchedulerOtpVerifyResponse.self, from: response)
    return result.token
  }

  func fetchSchedulerHome(token: String, start: Date, end: Date) async throws -> NativeSchedulerHomeResponse {
    var components = URLComponents(url: baseURL.appendingPathComponent("/api/native/scheduler/home"), resolvingAgainstBaseURL: false)!
    components.queryItems = [
      URLQueryItem(name: "start", value: isoDate(start)),
      URLQueryItem(name: "end", value: isoDate(end))
    ]
    guard let url = components.url else { throw NativeCALError.invalidURL }

    var request = URLRequest(url: url)
    request.httpMethod = "GET"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerHomeResponse.self, from: data)
  }

  func fetchSchedulerBlock(token: String, blockId: Int) async throws -> NativeSchedulerBlockDetailResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/blocks/\(blockId)")
    var request = URLRequest(url: url)
    request.httpMethod = "GET"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerBlockDetailResponse.self, from: data)
  }

  func assignSchedulerBlock(token: String, blockId: Int, surgeonId: Int, startTime: String, caseCount: Int, note: String) async throws -> NativeSchedulerAssignResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/blocks/\(blockId)/assign")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.httpBody = try JSONEncoder().encode(NativeSchedulerAssignPayload(
      surgeonId: surgeonId,
      startTime: startTime,
      caseCount: caseCount,
      note: note
    ))

    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerAssignResponse.self, from: data)
  }

  func updateSchedulerAssignment(
    token: String,
    blockId: Int,
    assignmentId: Int,
    surgeonId: Int,
    startTime: String,
    caseCount: Int,
    note: String
  ) async throws -> NativeSchedulerAssignResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/blocks/\(blockId)/assignments/\(assignmentId)/update")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.httpBody = try JSONEncoder().encode(NativeSchedulerAssignPayload(
      surgeonId: surgeonId,
      startTime: startTime,
      caseCount: caseCount,
      note: note
    ))

    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerAssignResponse.self, from: data)
  }

  func clearSchedulerBlock(token: String, blockId: Int) async throws -> NativeSchedulerAssignResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/blocks/\(blockId)/clear")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerAssignResponse.self, from: data)
  }

  func removeSchedulerAssignment(token: String, blockId: Int, assignmentId: Int) async throws -> NativeSchedulerAssignResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/blocks/\(blockId)/assignments/\(assignmentId)/remove")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerAssignResponse.self, from: data)
  }

  func fetchSchedulerMeta(token: String) async throws -> NativeSchedulerMetaResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/meta")
    var request = URLRequest(url: url)
    request.httpMethod = "GET"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerMetaResponse.self, from: data)
  }

  func createSchedulerBlock(
    token: String,
    date: String,
    locationId: Int,
    session: String,
    startTime: String?,
    endTime: String?,
    notes: String
  ) async throws -> NativeSchedulerCreateBlockResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/blocks")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.httpBody = try JSONEncoder().encode(NativeSchedulerCreateBlockPayload(
      date: date,
      locationId: locationId,
      session: session,
      startTime: startTime,
      endTime: endTime,
      notes: notes
    ))
    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerCreateBlockResponse.self, from: data)
  }

  func updateSchedulerBlock(
    token: String,
    blockId: Int,
    locationId: Int?,
    session: String?,
    startTime: String?,
    endTime: String?,
    notes: String?
  ) async throws -> NativeSchedulerAssignResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/blocks/\(blockId)")
    var request = URLRequest(url: url)
    request.httpMethod = "PATCH"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.httpBody = try JSONEncoder().encode(NativeSchedulerUpdateBlockPayload(
      locationId: locationId,
      session: session,
      startTime: startTime,
      endTime: endTime,
      notes: notes
    ))
    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerAssignResponse.self, from: data)
  }

  func deleteSchedulerBlock(token: String, blockId: Int) async throws -> NativeSchedulerDeleteBlockResponse {
    let url = baseURL.appendingPathComponent("/api/native/scheduler/blocks/\(blockId)")
    var request = URLRequest(url: url)
    request.httpMethod = "DELETE"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    let data = try await perform(request)
    return try JSONDecoder().decode(NativeSchedulerDeleteBlockResponse.self, from: data)
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

  func fetchPatientSchedule(token: String, start: Date, end: Date) async throws -> NativePatientScheduleResponse {
    var components = URLComponents(url: baseURL.appendingPathComponent("/api/native/patient-schedule"), resolvingAgainstBaseURL: false)!
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
    return try JSONDecoder().decode(NativePatientScheduleResponse.self, from: data)
  }

  func submitRequestOff(token: String, startDate: Date, endDate: Date, reason: String, notes: String, segments: [RequestSegment]) async throws -> [String] {
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
    return result.warnings
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

  func cancelCallCoverage(token: String, coverageId: Int) async throws -> NativeCallAssignmentResponse {
    let url = baseURL.appendingPathComponent("/api/native/call-coverage/\(coverageId)/cancel")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.setValue(token, forHTTPHeaderField: "X-CAL-Device-Token")
    let data = try await perform(request)
    let result = try JSONDecoder().decode(NativeCallCoverageResponse.self, from: data)
    return result.assignment
  }

  func markAlertsRead(token: String) async throws {
    let url = baseURL.appendingPathComponent("/api/native/alerts/read")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.setValue(token, forHTTPHeaderField: "X-CAL-Device-Token")
    _ = try await perform(request)
  }

  func registerPushToken(token: String, pushToken: String, platform: String = "ios", provider: String = "apns", deviceName: String? = nil) async throws {
    let url = baseURL.appendingPathComponent("/api/native/push-token")
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.setValue(token, forHTTPHeaderField: "X-CAL-Device-Token")
    request.httpBody = try JSONEncoder().encode(NativePushTokenPayload(
      token: pushToken,
      platform: platform,
      provider: provider,
      deviceName: deviceName
    ))
    _ = try await perform(request)
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
      if status == 401 {
        return body.contains("Invalid code") ? "Invalid code. Please try again." : "For security, please sign in again."
      }
      return NativeCALError.readableMessage(from: body) ?? "CAL request failed. Please try again."
    case .keychain(let status):
      return "Could not save sign-in token. Keychain status \(status)."
    case .missingSession:
      return "Sign in is needed before submitting."
    case .requestRejected(let message):
      return message.isEmpty ? "Request was not submitted." : message
    }
  }

  private static func readableMessage(from body: String) -> String? {
    guard let data = body.data(using: .utf8),
          let payload = try? JSONDecoder().decode(APIErrorPayload.self, from: data) else {
      return body.isEmpty ? nil : body
    }
    return payload.detail ?? payload.message
  }

  var isAuthenticationFailure: Bool {
    if case .http(let status, _) = self {
      return status == 401
    }
    return false
  }
}

private struct APIErrorPayload: Decodable {
  let detail: String?
  let message: String?
}

private struct NativePushTokenPayload: Encodable {
  let token: String
  let platform: String
  let provider: String
  let deviceName: String?
}
