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

struct NativeHomeResponse: Decodable {
  let surgeon: NativeSurgeon?
  let days: [NativeDayResponse]
  let requests: [NativeDayOffRequestResponse]
  let patients: NativePatientsResponse?
  let surgeons: [NativeSurgeon]?
}

struct OtpRequestPayload: Encodable {
  let email: String
}

struct OtpVerifyPayload: Encodable {
  let email: String
  let code: String
}

struct OtpRequestResponse: Decodable {
  let message: String?
}

struct OtpVerifyResponse: Decodable {
  let token: String
}

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
}

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

struct NativeDayResponse: Decodable {
  let date: String
  let dayName: String?
  let dayShort: String?
  let dayFull: String?
  let items: [NativeScheduleItemResponse]?
  let offSurgeons: [NativeOffSurgeonResponse]
  let callAssignments: [NativeCallAssignmentResponse]

  var scheduleDay: ScheduleDay {
    let parsedDate = Self.dateFormatter.date(from: date) ?? Date()
    let scheduleItems = (items ?? [])
      .compactMap { $0.doctorScheduleItem(dateKey: date) }
    let meetingItems = (items ?? [])
      .compactMap { $0.meetingItem(dateKey: date) }
    let personal = (items ?? [])
      .filter { $0.type == "personal" }
      .map(\.personalDisplayTitle)

    return ScheduleDay(
      id: dateKey(parsedDate),
      date: parsedDate,
      assignments: callAssignments.map { $0.scheduleAssignment(dateKey: date) },
      off: offSurgeons.map(\.initials),
      mySchedule: scheduleItems.isEmpty ? ScheduleFixtures.doctorScheduleFallback(for: parsedDate) : scheduleItems,
      meetings: meetingItems,
      personalItems: personal
    )
  }

  static let dateFormatter: DateFormatter = {
    let formatter = DateFormatter()
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = Calendar.current.timeZone
    formatter.dateFormat = "yyyy-MM-dd"
    return formatter
  }()
}

struct NativeDayOffRequestResponse: Decodable {
  let id: Int
  let surgeonInitials: String?
  let startDate: String
  let endDate: String
  let reason: String
  let status: String

  var timeOffRequest: TimeOffRequest {
    TimeOffRequest(
      id: id,
      surgeonInitials: surgeonInitials ?? "",
      startDate: startDate,
      endDate: endDate,
      reason: reason,
      status: status
    )
  }
}

struct NativePatientsResponse: Decodable {
  let today: NativePatientSummaryResponse
  let upcoming: [NativePatientSummaryResponse]
}

struct NativePatientSummaryResponse: Decodable {
  let date: String
  let count: Int
  let notes: String
  let location: String

  var patientSummary: PatientSummary {
    PatientSummary(
      id: date,
      date: date,
      count: count,
      notes: notes,
      location: location
    )
  }
}

struct NativeScheduleItemResponse: Decodable {
  let id: String?
  let rawId: Int?
  let type: String
  let title: String
  let subtitle: String?
  let start: String?
  let end: String?
  let allDay: Bool?
  let location: String?
  let room: String?
  let notes: String?

  func doctorScheduleItem(dateKey: String) -> DoctorScheduleItem? {
    guard !["personal", "meeting", "oncall", "dayoff"].contains(type), allDay != true else {
      return nil
    }

    return DoctorScheduleItem(
      id: id ?? "\(dateKey)-\(rawId ?? 0)-\(title)",
      period: periodLabel,
      title: displayTitle,
      subtitle: [location, room, subtitle].compactMap { value in
        guard let value, !value.isEmpty else { return nil }
        return value
      }.joined(separator: " · "),
      timeRange: timeRange
    )
  }

  func meetingItem(dateKey: String) -> DoctorScheduleItem? {
    guard type == "meeting" else { return nil }
    return DoctorScheduleItem(
      id: id ?? "\(dateKey)-meeting-\(rawId ?? 0)-\(title)",
      period: "MTG",
      title: title.isEmpty ? "Meeting" : title,
      subtitle: [location, room, subtitle, notes].compactMap { value in
        guard let value, !value.isEmpty else { return nil }
        return value
      }.joined(separator: " · "),
      timeRange: timeRange
    )
  }

  var personalDisplayTitle: String {
    [title, displayTime(start)]
      .filter { !$0.isEmpty }
      .joined(separator: " ")
  }

  private var displayTitle: String {
    switch type {
    case "clinic":
      return title.isEmpty ? "Clinic" : title
    case "surgery":
      return title.isEmpty ? "Hospital" : title
    case "patients":
      return title.isEmpty ? "Patients" : title
    default:
      return title
    }
  }

  private var periodLabel: String {
    guard let start else { return "DAY" }
    return start < "12:00" ? "AM" : "PM"
  }

  private var timeRange: String {
    let startText = displayTime(start)
    let endText = displayTime(end)
    if startText.isEmpty { return "" }
    if endText.isEmpty { return startText }
    return "\(startText) - \(endText)"
  }

  private func displayTime(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "" }
    let parts = value.split(separator: ":")
    guard let hourText = parts.first, let hour24 = Int(hourText) else {
      return value
    }
    let minute = parts.count > 1 ? String(parts[1]) : "00"
    let hour12 = hour24 % 12 == 0 ? 12 : hour24 % 12
    return "\(hour12):\(minute)"
  }
}

struct NativeOffSurgeonResponse: Decodable {
  let initials: String
}

struct NativeCallAssignmentResponse: Decodable {
  let rotationId: Int
  let surgeonId: Int?
  let group: String
  let surgeon: String
  let initials: String?
  let originalInitials: String?
  let originalSurgeonId: Int?
  let coveringInitials: String?
  let coveringSurgeonId: Int?
  let isCovered: Bool?

  func scheduleAssignment(dateKey: String) -> ScheduleAssignment {
    let displayedInitials = coveringInitials ?? initials ?? surgeonInitials(from: surgeon)
    return ScheduleAssignment(
      id: "\(dateKey)-\(rotationId)",
      rotationId: rotationId,
      location: group,
      locationShort: shortGroupName(group),
      surgeon: displayedInitials,
      surgeonId: surgeonId,
      originalInitials: originalInitials ?? initials ?? surgeonInitials(from: surgeon),
      originalSurgeonId: originalSurgeonId ?? surgeonId,
      coveringInitials: coveringInitials,
      coveringSurgeonId: coveringSurgeonId,
      isCovered: isCovered == true,
      time: "7:00 AM - 5:00 PM",
      systemImage: "building.2"
    )
  }

  private func surgeonInitials(from name: String) -> String {
    let parts = name.split(separator: " ")
    let letters = parts.prefix(2).compactMap { $0.first }
    return letters.isEmpty ? name : String(letters).uppercased()
  }

  private func shortGroupName(_ group: String) -> String {
    let upper = group.uppercased()
    if upper.contains("WINTER") || upper.contains("APOPKA") || upper.contains("MINNEOLA") {
      return "WG / A / Minneola"
    }
    if upper.contains("ALTAMONTE") {
      return "Altamonte Hosp"
    }
    return group
  }
}

func dateKey(_ date: Date) -> String {
  let components = Calendar.current.dateComponents([.year, .month, .day], from: date)
  return "\(components.year ?? 0)-\(components.month ?? 0)-\(components.day ?? 0)"
}
