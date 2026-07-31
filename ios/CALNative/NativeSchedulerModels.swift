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
  let room: String
  let surgeonId: Int?
  let surgeon: String?
  let surgeonInitials: String
  let assignedStart: String?
  let caseCount: Int
  let assignmentNote: String
  let assignmentLabel: String
  let assignments: [NativeSchedulerBlockAssignment]
  let cases: [NativeSchedulerCase]
  let notes: String

  var isOpen: Bool { status == "open" }

  var displayLocation: String {
    locationAbbreviation.isEmpty ? location : locationAbbreviation
  }

  var displayRoom: String {
    let trimmed = room.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty ? "" : trimmed
  }

  var displayDate: String {
    guard let parsed = NativeDayResponse.dateFormatter.date(from: date) else { return date }
    return parsed.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
  }

  enum CodingKeys: String, CodingKey {
    case id, date, session, start, end, status, locationId, location, locationAbbreviation
    case room, surgeonId, surgeon, surgeonInitials, assignedStart, caseCount
    case assignmentNote, assignmentLabel, assignments, cases, notes
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    id = try container.decode(Int.self, forKey: .id)
    date = try container.decode(String.self, forKey: .date)
    session = try container.decode(String.self, forKey: .session)
    start = try container.decode(String.self, forKey: .start)
    end = try container.decode(String.self, forKey: .end)
    status = try container.decode(String.self, forKey: .status)
    locationId = try container.decode(Int.self, forKey: .locationId)
    location = try container.decodeIfPresent(String.self, forKey: .location) ?? ""
    locationAbbreviation = try container.decodeIfPresent(String.self, forKey: .locationAbbreviation) ?? ""
    room = try container.decodeIfPresent(String.self, forKey: .room) ?? ""
    surgeonId = try container.decodeIfPresent(Int.self, forKey: .surgeonId)
    surgeon = try container.decodeIfPresent(String.self, forKey: .surgeon)
    surgeonInitials = try container.decodeIfPresent(String.self, forKey: .surgeonInitials) ?? ""
    assignedStart = try container.decodeIfPresent(String.self, forKey: .assignedStart)
    caseCount = try container.decodeIfPresent(Int.self, forKey: .caseCount) ?? 0
    assignmentNote = try container.decodeIfPresent(String.self, forKey: .assignmentNote) ?? ""
    assignmentLabel = try container.decodeIfPresent(String.self, forKey: .assignmentLabel) ?? ""
    assignments = try container.decodeIfPresent([NativeSchedulerBlockAssignment].self, forKey: .assignments) ?? []
    cases = try container.decodeIfPresent([NativeSchedulerCase].self, forKey: .cases) ?? []
    notes = try container.decodeIfPresent(String.self, forKey: .notes) ?? ""
  }
}

struct NativeSchedulerCase: Identifiable, Decodable {
  let id: Int
  let surgeonId: Int?
  let start: String
  let end: String
  let procedure: String
  let patientName: String
  let room: String

  var timeLabel: String {
    if start.isEmpty { return "—" }
    if end.isEmpty { return start }
    return "\(start)–\(end)"
  }

  var detailLine: String {
    [procedure, patientName]
      .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
      .filter { !$0.isEmpty }
      .joined(separator: " · ")
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
  let room: String

  enum CodingKeys: String, CodingKey {
    case id, surgeonId, surgeon, surgeonInitials, start, caseCount, note, label, room
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    id = try container.decode(Int.self, forKey: .id)
    surgeonId = try container.decode(Int.self, forKey: .surgeonId)
    surgeon = try container.decodeIfPresent(String.self, forKey: .surgeon) ?? ""
    surgeonInitials = try container.decodeIfPresent(String.self, forKey: .surgeonInitials) ?? ""
    start = try container.decodeIfPresent(String.self, forKey: .start) ?? ""
    caseCount = try container.decodeIfPresent(Int.self, forKey: .caseCount) ?? 0
    note = try container.decodeIfPresent(String.self, forKey: .note) ?? ""
    label = try container.decodeIfPresent(String.self, forKey: .label) ?? ""
    room = try container.decodeIfPresent(String.self, forKey: .room) ?? ""
  }
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

struct NativeSchedulerCasePayload: Encodable {
  let surgeonId: Int
  let startTime: String
  let endTime: String?
  let procedure: String
  let patientName: String

  enum CodingKeys: String, CodingKey {
    case surgeonId = "surgeon_id"
    case startTime = "start_time"
    case endTime = "end_time"
    case procedure
    case patientName = "patient_name"
  }
}

struct NativeSchedulerCaseUpdatePayload: Encodable {
  let startTime: String?
  let endTime: String?
  let procedure: String?
  let patientName: String?
  let surgeonId: Int?
  let targetBlockId: Int?

  enum CodingKeys: String, CodingKey {
    case startTime = "start_time"
    case endTime = "end_time"
    case procedure
    case patientName = "patient_name"
    case surgeonId = "surgeon_id"
    case targetBlockId = "target_block_id"
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
