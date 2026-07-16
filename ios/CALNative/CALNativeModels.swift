import Foundation

enum ScheduleScope: String, CaseIterable, Identifiable {
  case day = "Day"
  case week = "Week"
  case month = "Month"

  var id: String { rawValue }
}

enum NativeSessionRole: String {
  case surgeon
  case scheduler
}

struct NativeVerifiedSession {
  let token: String
  let role: NativeSessionRole
}

struct ScheduleAssignment: Identifiable {
  let id: String
  let rotationId: Int?
  let coverageId: Int?
  let location: String
  let locationShort: String
  let surgeon: String
  let surgeonId: Int?
  let originalInitials: String
  let originalSurgeonId: Int?
  let coveringInitials: String?
  let coveringSurgeonId: Int?
  let isCovered: Bool
  let time: String
  let systemImage: String
}

struct NativeSurgeon: Identifiable, Decodable {
  let id: Int
  let name: String
  let initials: String
  let staffType: String
  let sortOrder: Int?

  enum CodingKeys: String, CodingKey {
    case id
    case name
    case initials
    case staffType
    case sortOrder
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    id = try container.decode(Int.self, forKey: .id)
    name = try container.decode(String.self, forKey: .name)
    initials = try container.decodeIfPresent(String.self, forKey: .initials) ?? Self.initials(from: name)
    staffType = try container.decodeIfPresent(String.self, forKey: .staffType) ?? "physician"
    sortOrder = try container.decodeIfPresent(Int.self, forKey: .sortOrder)
  }

  private static func initials(from name: String) -> String {
    let parts = name.split(separator: " ")
    let letters = parts.prefix(2).compactMap { $0.first }
    return letters.isEmpty ? name : String(letters).uppercased()
  }
}

struct NativeScheduleAlert: Identifiable, Decodable {
  let id: Int
  let title: String
  let body: String
  let kind: String
  let isRead: Bool
  let createdAt: String

  var createdDate: Date? {
    ISO8601DateFormatter().date(from: createdAt)
  }

  var displayTime: String {
    guard let createdDate else { return "" }
    return createdDate.formatted(.dateTime.month(.abbreviated).day().hour().minute())
  }
}

struct NativeAlertSummary: Decodable {
  let unreadCount: Int
  let recent: [NativeScheduleAlert]
}

struct DoctorScheduleItem: Identifiable {
  let id: String
  let period: String
  let title: String
  let subtitle: String
  let timeRange: String
  /// Native item type: clinic, surgery, block_or, meeting, …
  let kind: String

  var isBlockOr: Bool { kind == "block_or" }
  var isClinicOrSurgery: Bool { kind == "clinic" || kind == "surgery" }
}

struct ScheduleDay: Identifiable {
  let id: String
  let date: Date
  let assignments: [ScheduleAssignment]
  let off: [String]
  let requestedOff: [String]
  let mySchedule: [DoctorScheduleItem]
  let meetings: [DoctorScheduleItem]
  let personalItems: [String]
  /// Logged-in surgeon's approved Day Off (from home `dayoff` items).
  let hasMyApprovedOff: Bool
  let hasClinicOr: Bool
  let hasBlockTime: Bool
  let hasMeeting: Bool

  var summary: String {
    if assignments.isEmpty {
      return "No on-call coverage"
    }
    return "\(assignments.count) on call"
  }

  static func empty(for date: Date) -> ScheduleDay {
    ScheduleDay(
      id: dateKey(date),
      date: date,
      assignments: [],
      off: [],
      requestedOff: [],
      mySchedule: [],
      meetings: [],
      personalItems: [],
      hasMyApprovedOff: false,
      hasClinicOr: false,
      hasBlockTime: false,
      hasMeeting: false
    )
  }
}

struct TimeOffRequest: Identifiable {
  let id: Int
  let surgeonInitials: String
  let startDate: String
  let endDate: String
  let reason: String
  let status: String

  var dateRange: String {
    if startDate == endDate {
      return formatShortDate(startDate)
    }
    return "\(formatShortDate(startDate)) - \(formatShortDate(endDate))"
  }

  private func formatShortDate(_ iso: String) -> String {
    guard let date = NativeDayResponse.dateFormatter.date(from: iso) else {
      return iso
    }
    return date.formatted(.dateTime.month(.twoDigits).day(.twoDigits))
  }
}

struct PatientAppointment: Identifiable {
  let id: String
  let date: Date
  let start: String
  let end: String
  let surgeonInitials: String
  let surgeonName: String
  let patientName: String
  let mrn: String
  let appointmentType: String
  let status: String
  let reason: String
  let serviceSite: String
  let room: String

  var timeRange: String {
    let startText = displayTime(start)
    let endText = displayTime(end)
    if startText.isEmpty { return "" }
    if endText.isEmpty { return startText }
    return "\(startText) - \(endText)"
  }

  var locationLine: String {
    [serviceSite, room].filter { !$0.isEmpty }.joined(separator: " · ")
  }

  private func displayTime(_ value: String) -> String {
    guard !value.isEmpty else { return "" }
    let parts = value.split(separator: ":")
    guard let hourText = parts.first, let hour24 = Int(hourText) else {
      return value
    }
    let minute = parts.count > 1 ? String(parts[1]) : "00"
    return "\(String(format: "%02d", hour24)):\(minute)"
  }
}

struct RequestSegment: Identifiable {
  let date: Date
  let isFullDay: Bool
  let start: String
  let end: String

  var id: String {
    dateKey(date)
  }

  var preset: RequestSegmentPreset {
    if isFullDay {
      return .full
    }
    if start == "07:00", end == "12:00" {
      return .am
    }
    if start == "12:00", end == "17:00" {
      return .pm
    }
    return .full
  }

  var summary: String {
    isFullDay ? "Full day" : "\(displayTime(start)) - \(displayTime(end))"
  }

  private func displayTime(_ value: String) -> String {
    switch value {
    case "07:00":
      return "07:00"
    case "12:00":
      return "12:00"
    case "17:00":
      return "17:00"
    default:
      return value
    }
  }
}

enum RequestSegmentPreset: String, CaseIterable, Identifiable {
  case full
  case am
  case pm

  var id: String { rawValue }

  var label: String {
    switch self {
    case .full:
      return "Full"
    case .am:
      return "AM"
    case .pm:
      return "PM"
    }
  }
}

struct MonthCell: Identifiable {
  let id: String
  let date: Date
  let isCurrentMonth: Bool
  let isToday: Bool
  let assignments: [ScheduleAssignment]
  let callInitials: [String]
  let offInitials: [String]
  let schedulePeriods: [String]
  let hasMyApprovedOff: Bool
  let hasClinicOr: Bool
  let hasBlockTime: Bool
  let hasMeeting: Bool

  var callSummary: String {
    summarized(callInitials, limit: 2)
  }

  var offSummary: String {
    summarized(offInitials, limit: 2)
  }

  var scheduleSummary: String {
    schedulePeriods.prefix(2).joined(separator: "/")
  }

  private func summarized(_ values: [String], limit: Int) -> String {
    let visible = values.prefix(limit).joined(separator: "/")
    let hiddenCount = values.count - min(values.count, limit)
    guard hiddenCount > 0 else { return visible }
    return "\(visible)+\(hiddenCount)"
  }

  static func empty(for date: Date, isCurrentMonth: Bool, isToday: Bool) -> MonthCell {
    MonthCell(
      id: dateKey(date),
      date: date,
      isCurrentMonth: isCurrentMonth,
      isToday: isToday,
      assignments: [],
      callInitials: [],
      offInitials: [],
      schedulePeriods: [],
      hasMyApprovedOff: false,
      hasClinicOr: false,
      hasBlockTime: false,
      hasMeeting: false
    )
  }
}

struct DateRange {
  let start: Date
  let end: Date

  init(containing date: Date, scope: ScheduleScope) {
    let calendar = Calendar.current

    switch scope {
    case .day:
      start = calendar.startOfDay(for: date)
      end = calendar.startOfDay(for: date)
    case .week:
      let interval = calendar.dateInterval(of: .weekOfYear, for: date)
      start = interval?.start ?? calendar.startOfDay(for: date)
      end = calendar.date(byAdding: .day, value: 6, to: start) ?? start
    case .month:
      let interval = calendar.dateInterval(of: .month, for: date)
      start = interval?.start ?? calendar.startOfDay(for: date)
      end = calendar.date(byAdding: DateComponents(month: 1, day: -1), to: start) ?? start
    }
  }
}

func dateKey(_ date: Date) -> String {
  let components = Calendar.current.dateComponents([.year, .month, .day], from: date)
  return "\(components.year ?? 0)-\(components.month ?? 0)-\(components.day ?? 0)"
}
