import Foundation

struct TimeOffSubmitPayload: Encodable {
  let startDate: String
  let endDate: String
  let reason: String
  let notes: String
  let isFullDay: Bool
  let start: String?
  let end: String?
  let segments: [TimeOffSubmitSegment]

  enum CodingKeys: String, CodingKey {
    case startDate = "start_date"
    case endDate = "end_date"
    case reason
    case notes
    case isFullDay = "is_full_day"
    case start
    case end
    case segments
  }
}

struct TimeOffSubmitSegment: Encodable {
  let date: String
  let isFullDay: Bool
  let start: String
  let end: String
}

struct NativeRequestOffResponse: Decodable {
  let ok: Bool
  let warnings: [String]
  let emailed: Bool

  enum CodingKeys: String, CodingKey {
    case ok
    case warnings
    case emailed
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    ok = try container.decode(Bool.self, forKey: .ok)
    warnings = try container.decodeIfPresent([String].self, forKey: .warnings) ?? []
    emailed = try container.decodeIfPresent(Bool.self, forKey: .emailed) ?? false
  }
}

struct TimeOffSubmitResult {
  let warnings: [String]
  let emailed: Bool
}
