import Foundation

enum ScheduleScope: String, CaseIterable, Identifiable {
  case day = "Day"
  case week = "Week"
  case month = "Month"

  var id: String { rawValue }
}

struct ScheduleAssignment: Identifiable {
  let id: String
  let rotationId: Int?
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

struct DoctorScheduleItem: Identifiable {
  let id: String
  let period: String
  let title: String
  let subtitle: String
  let timeRange: String
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
      personalItems: []
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
      return "7:00 AM"
    case "12:00":
      return "12:00 PM"
    case "17:00":
      return "5:00 PM"
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
      schedulePeriods: []
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
