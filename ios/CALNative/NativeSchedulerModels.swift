import Foundation

struct NativeSchedulerHomeResponse: Decodable {
  let range: NativeSchedulerRange
  let blocks: [NativeSchedulerBlock]
  let changes: [NativeSchedulerChange]
}

struct NativeSchedulerRange: Decodable {
  let start: String
  let end: String
}

struct NativeSchedulerBlock: Identifiable, Decodable {
  let id: Int
  let date: String
  let session: String
  let start: String
  let end: String
  let status: String
  let locationId: Int
  let location: String
  let locationAbbreviation: String
  let surgeonId: Int?
  let surgeon: String?
  let surgeonInitials: String
  let assignedStart: String?
  let caseCount: Int
  let assignmentNote: String
  let assignmentLabel: String
  let assignments: [NativeSchedulerBlockAssignment]
  let notes: String

  var isOpen: Bool { status == "open" }

  var displayLocation: String {
    locationAbbreviation.isEmpty ? location : locationAbbreviation
  }

  var displayDate: String {
    guard let parsed = NativeDayResponse.dateFormatter.date(from: date) else { return date }
    return parsed.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
  }
}

struct NativeSchedulerBlockAssignment: Identifiable, Decodable {
  let id: Int
  let surgeonId: Int
  let surgeon: String
  let surgeonInitials: String
  let start: String
  let caseCount: Int
  let note: String
  let label: String
}

struct NativeSchedulerBlockDetailResponse: Decodable {
  let block: NativeSchedulerBlock
  let candidates: [NativeSchedulerCandidate]
}

struct NativeSchedulerCandidate: Identifiable, Decodable {
  let surgeonId: Int
  let name: String
  let initials: String
  let status: String
  let availability: String
  let warnings: [String]

  var id: Int { surgeonId }
  var isClear: Bool { warnings.isEmpty }
}

struct NativeSchedulerAssignResponse: Decodable {
  let ok: Bool
  let block: NativeSchedulerBlock
  let warnings: [String]
}

struct NativeSchedulerAssignPayload: Encodable {
  let surgeonId: Int
  let startTime: String
  let caseCount: Int
  let note: String

  enum CodingKeys: String, CodingKey {
    case surgeonId = "surgeon_id"
    case startTime = "start_time"
    case caseCount = "case_count"
    case note
  }
}

struct NativeSchedulerChange: Identifiable, Decodable {
  let id: Int
  let type: String
  let date: String?
  let title: String
  let body: String
  let surgeon: String
  let surgeonInitials: String
  let createdAt: String
}

struct NativeSchedulerHospital: Identifiable, Decodable, Hashable {
  let id: Int
  let name: String
  let abbreviation: String

  var displayName: String {
    abbreviation.isEmpty ? name : "\(abbreviation) — \(name)"
  }
}

struct NativeSchedulerSessionOption: Identifiable, Decodable, Hashable {
  let id: String
  let label: String
  let start: String
  let end: String
}

struct NativeSchedulerMetaResponse: Decodable {
  let hospitals: [NativeSchedulerHospital]
  let sessions: [NativeSchedulerSessionOption]
}

struct NativeSchedulerCreateBlockPayload: Encodable {
  let date: String
  let locationId: Int
  let session: String
  let startTime: String?
  let endTime: String?
  let notes: String

  enum CodingKeys: String, CodingKey {
    case date
    case locationId = "location_id"
    case session
    case startTime = "start_time"
    case endTime = "end_time"
    case notes
  }
}

struct NativeSchedulerUpdateBlockPayload: Encodable {
  let locationId: Int?
  let session: String?
  let startTime: String?
  let endTime: String?
  let notes: String?

  enum CodingKeys: String, CodingKey {
    case locationId = "location_id"
    case session
    case startTime = "start_time"
    case endTime = "end_time"
    case notes
  }
}

struct NativeSchedulerCreateBlockResponse: Decodable {
  let ok: Bool
  let created: Int
  let blockIds: [Int]
  let blocks: [NativeSchedulerBlock]
}

struct NativeSchedulerDeleteBlockResponse: Decodable {
  let ok: Bool
  let deleted: Bool
  let blockId: Int
}
