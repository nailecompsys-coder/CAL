import Foundation

struct NativeCallCoveragePayload: Encodable {
  let rotationId: Int
  let coveringSurgeonId: Int
  let notes: String

  enum CodingKeys: String, CodingKey {
    case rotationId = "rotation_id"
    case coveringSurgeonId = "covering_surgeon_id"
    case notes
  }
}

struct NativeCallCoverageResponse: Decodable {
  let ok: Bool
  let assignment: NativeCallAssignmentResponse
}
