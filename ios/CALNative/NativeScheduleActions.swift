import Foundation

struct NativeScheduleActions {
  private let client: NativeCALClient

  init(client: NativeCALClient = NativeCALClient()) {
    self.client = client
  }

  func submitTimeOffRequest(
    token: String,
    startDate: Date,
    endDate: Date,
    reason: String,
    notes: String,
    segments: [RequestSegment]
  ) async throws -> [String] {
    guard !token.isEmpty else {
      throw NativeCALError.missingSession
    }

    return try await client.submitRequestOff(
      token: token,
      startDate: startDate,
      endDate: endDate,
      reason: reason,
      notes: notes,
      segments: segments
    )
  }

  func submitCallCoverage(
    token: String,
    assignment: ScheduleAssignment,
    coveringSurgeon: NativeSurgeon
  ) async throws {
    guard !token.isEmpty else {
      throw NativeCALError.missingSession
    }
    guard let rotationId = assignment.rotationId else {
      throw NativeCALError.requestRejected("This on-call row is not linked to the live schedule and cannot be updated.")
    }

    _ = try await client.submitCallCoverage(
      token: token,
      rotationId: rotationId,
      coveringSurgeonId: coveringSurgeon.id
    )
  }

  func cancelCallCoverage(
    token: String,
    assignment: ScheduleAssignment
  ) async throws {
    guard !token.isEmpty else {
      throw NativeCALError.missingSession
    }
    guard let coverageId = assignment.coverageId else {
      throw NativeCALError.requestRejected("This coverage row is not linked and cannot be cleared.")
    }

    _ = try await client.cancelCallCoverage(
      token: token,
      coverageId: coverageId
    )
  }
}
