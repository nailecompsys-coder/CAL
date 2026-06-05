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

struct PatientSummary: Identifiable {
  let id: String
  let date: String
  let count: Int
  let notes: String
  let location: String

  var subtitle: String {
    [formatShortDate(date), location, notes]
      .filter { !$0.isEmpty }
      .joined(separator: " · ")
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
}

enum ScheduleFixtures {
  static func day(for date: Date) -> ScheduleDay {
    let calendar = Calendar.current
    let dayNumber = calendar.component(.day, from: date)
    let assignments = assignments(for: dayNumber)

    return ScheduleDay(
      id: dateKey(date),
      date: date,
      assignments: assignments,
      off: offInitials(for: dayNumber),
      requestedOff: [],
      mySchedule: doctorSchedule(for: dayNumber),
      meetings: meetings(for: dayNumber),
      personalItems: personalItems(for: dayNumber)
    )
  }

  static func week(containing date: Date) -> [ScheduleDay] {
    let calendar = Calendar.current
    let interval = calendar.dateInterval(of: .weekOfYear, for: date)
    let start = interval?.start ?? calendar.startOfDay(for: date)

    return (0..<7).compactMap { offset in
      guard let dayDate = calendar.date(byAdding: .day, value: offset, to: start) else { return nil }
      return day(for: dayDate)
    }
  }

  static func month(containing date: Date) -> [MonthCell] {
    let calendar = Calendar.current
    guard let monthInterval = calendar.dateInterval(of: .month, for: date) else { return [] }

    let firstOfMonth = monthInterval.start
    let leadingDays = calendar.component(.weekday, from: firstOfMonth) - 1
    let gridStart = calendar.date(byAdding: .day, value: -leadingDays, to: firstOfMonth) ?? firstOfMonth

    return (0..<42).compactMap { offset in
      guard let cellDate = calendar.date(byAdding: .day, value: offset, to: gridStart) else { return nil }
      let day = self.day(for: cellDate)
      return MonthCell(
        id: dateKey(cellDate),
        date: cellDate,
        isCurrentMonth: calendar.isDate(cellDate, equalTo: date, toGranularity: .month),
        isToday: calendar.isDateInToday(cellDate),
        assignments: day.assignments,
        callInitials: day.assignments.map(\.surgeon),
        offInitials: day.off,
        schedulePeriods: day.mySchedule.map(\.period)
      )
    }
  }

  private static func assignments(for dayNumber: Int) -> [ScheduleAssignment] {
    let westSurgeon = ["LW", "JP", "AS", "JF", "OK"][dayNumber % 5]
    let altamonteSurgeon = ["GY", "NF", "LN", "CJ"][dayNumber % 4]

    return [
      ScheduleAssignment(
        id: "fixture-west-\(dayNumber)",
        rotationId: nil,
        location: "Winter Garden / Apopka / Minneola",
        locationShort: "WG / A / Minneola",
        surgeon: westSurgeon,
        surgeonId: nil,
        originalInitials: westSurgeon,
        originalSurgeonId: nil,
        coveringInitials: nil,
        coveringSurgeonId: nil,
        isCovered: false,
        time: "7:00 AM - 5:00 PM",
        systemImage: "cross.case"
      ),
      ScheduleAssignment(
        id: "fixture-ah-\(dayNumber)",
        rotationId: nil,
        location: "Altamonte Hospital",
        locationShort: "Altamonte Hosp",
        surgeon: altamonteSurgeon,
        surgeonId: nil,
        originalInitials: altamonteSurgeon,
        originalSurgeonId: nil,
        coveringInitials: nil,
        coveringSurgeonId: nil,
        isCovered: false,
        time: "7:00 AM - 5:00 PM",
        systemImage: "building.2"
      )
    ]
  }

  private static func offInitials(for dayNumber: Int) -> [String] {
    if dayNumber % 7 == 0 { return ["LW", "GY", "NF"] }
    if dayNumber % 5 == 0 { return ["OK", "LW"] }
    if dayNumber % 3 == 0 { return ["LW"] }
    return []
  }

  private static func doctorSchedule(for dayNumber: Int) -> [DoctorScheduleItem] {
    [
      DoctorScheduleItem(
        id: "fixture-am-\(dayNumber)",
        period: "AM",
        title: "Clinic",
        subtitle: "Chris Johnson",
        timeRange: "8:00 - 12:00"
      ),
      DoctorScheduleItem(
        id: "fixture-pm-\(dayNumber)",
        period: "PM",
        title: "Hospital",
        subtitle: dayNumber % 2 == 0 ? "Altamonte Hosp" : "Winter Garden / Apopka",
        timeRange: "1:00 - 5:00"
      )
    ]
  }

  static func doctorScheduleFallback(for date: Date) -> [DoctorScheduleItem] {
    let dayNumber = Calendar.current.component(.day, from: date)
    return doctorSchedule(for: dayNumber)
  }

  private static func meetings(for dayNumber: Int) -> [DoctorScheduleItem] {
    if dayNumber % 2 == 0 {
      return [
        DoctorScheduleItem(
          id: "fixture-meeting-\(dayNumber)",
          period: "MTG",
          title: "Ops huddle",
          subtitle: "Main office",
          timeRange: "12:15"
        )
      ]
    }
    return []
  }

  static func meetingsFallback(for date: Date) -> [DoctorScheduleItem] {
    let dayNumber = Calendar.current.component(.day, from: date)
    return meetings(for: dayNumber)
  }

  private static func personalItems(for dayNumber: Int) -> [String] {
    if dayNumber % 6 == 0 { return ["No call note"] }
    if dayNumber % 4 == 0 { return ["Coverage reminder"] }
    return []
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
