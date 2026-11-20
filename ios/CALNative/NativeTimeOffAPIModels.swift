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
  /// "approved" when the request was inside the time-off rules; "pending" otherwise.
  let status: String?

  enum CodingKeys: String, CodingKey {
    case ok
    case warnings
    case emailed
    case status
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    ok = try container.decode(Bool.self, forKey: .ok)
    warnings = try container.decodeIfPresent([String].self, forKey: .warnings) ?? []
    emailed = try container.decodeIfPresent(Bool.self, forKey: .emailed) ?? false
    status = try container.decodeIfPresent(String.self, forKey: .status)
  }
}

/// Time-off groups preview: "clear", "yellow" or "red" plus the surgeon-facing message.
struct TimeOffCapacityPreview: Decodable, Equatable {
  let level: String
  let message: String
  let offList: [TimeOffPersonOff]
  let days: [TimeOffDayLine]

  var isRed: Bool { level == "red" }
  var isYellow: Bool { level == "yellow" }

  enum CodingKeys: String, CodingKey {
    case level
    case message
    case offList
    case days
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    level = try container.decode(String.self, forKey: .level)
    message = try container.decode(String.self, forKey: .message)
    offList = try container.decodeIfPresent([TimeOffPersonOff].self, forKey: .offList) ?? []
    days = try container.decodeIfPresent([TimeOffDayLine].self, forKey: .days) ?? []
  }
}

/// One requested day at yellow or red: how many would be off and who else.
struct TimeOffDayLine: Decodable, Equatable, Identifiable {
  let date: String
  let label: String
  let level: String
  let offCount: Int
  let others: [String]
  /// "2 cases booked" when the doctor already has clinic or OR work that day.
  let booked: String

  enum CodingKeys: String, CodingKey {
    case date, label, level, offCount, others, booked
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    date = try container.decode(String.self, forKey: .date)
    label = try container.decode(String.self, forKey: .label)
    level = try container.decode(String.self, forKey: .level)
    offCount = try container.decodeIfPresent(Int.self, forKey: .offCount) ?? 0
    others = try container.decodeIfPresent([String].self, forKey: .others) ?? []
    booked = try container.decodeIfPresent(String.self, forKey: .booked) ?? ""
  }

  var id: String { date }
  var isRed: Bool { level == "red" }
}

/// Someone else already off during the requested time (no patient data).
struct TimeOffPersonOff: Decodable, Equatable, Identifiable {
  let surgeonId: Int
  let initials: String
  let name: String
  let status: String
  let when: String

  var id: Int { surgeonId }
  var isApproved: Bool { status == "approved" }
}

struct TimeOffSubmitResult {
  let warnings: [String]
  let emailed: Bool
  var status: String? = nil

  var isApproved: Bool { status == "approved" }
}
