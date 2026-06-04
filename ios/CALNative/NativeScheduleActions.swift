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
  ) async throws {
    guard !token.isEmpty else {
      throw NativeCALError.missingSession
    }

    try await client.submitRequestOff(
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
      throw NativeCALError.requestRejected("This on-call row is preview data and cannot be updated.")
    }

    _ = try await client.submitCallCoverage(
      token: token,
      rotationId: rotationId,
      coveringSurgeonId: coveringSurgeon.id
    )
  }
}
