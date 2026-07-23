import Foundation

struct NativeHomeResponse: Decodable {
  let surgeon: NativeSurgeon?
  let days: [NativeDayResponse]
  let requests: [NativeDayOffRequestResponse]
  let surgeons: [NativeSurgeon]?
  let alerts: NativeAlertSummary?
}

struct NativePatientScheduleResponse: Decodable {
  let appointments: [NativePatientAppointmentResponse]
  let warning: String?
}

struct NativePatientAppointmentResponse: Decodable {
  let id: String?
  let date: String
  let start: String
  let end: String
  let surgeonInitials: String
  let surgeonName: String
  let patientName: String
  let mrn: String?
  let appointmentType: String
  let status: String
  let reason: String
  let serviceSite: String
  let room: String

  var patientAppointment: PatientAppointment {
    let parsedDate = NativeDayResponse.dateFormatter.date(from: date) ?? Date()
    return PatientAppointment(
      id: id ?? "\(date)-\(start)-\(patientName)",
      date: parsedDate,
      start: start,
      end: end,
      surgeonInitials: surgeonInitials,
      surgeonName: surgeonName,
      patientName: patientName,
      mrn: mrn ?? "",
      appointmentType: appointmentType,
      status: status,
      reason: reason,
      serviceSite: serviceSite,
      room: room
    )
  }
}

struct NativeDayResponse: Decodable {
  let date: String
  let dayName: String?
  let dayShort: String?
  let dayFull: String?
  let items: [NativeScheduleItemResponse]?
  let offSurgeons: [NativeOffSurgeonResponse]
  let requestedOffSurgeons: [NativeOffSurgeonResponse]?
  let callAssignments: [NativeCallAssignmentResponse]

  var scheduleDay: ScheduleDay {
    let parsedDate = Self.dateFormatter.date(from: date) ?? Date()
    let allItems = items ?? []
    let scheduleItems = allItems.compactMap { $0.doctorScheduleItem(dateKey: date) }
    let meetingItems = allItems.compactMap { $0.meetingItem(dateKey: date) }
    let personal = allItems
      .filter { $0.type == "personal" }
      .map(\.personalDisplayTitle)

    return ScheduleDay(
      id: dateKey(parsedDate),
      date: parsedDate,
      assignments: callAssignments.map { $0.scheduleAssignment(dateKey: date) },
      off: offSurgeons.map(\.initials),
      requestedOff: (requestedOffSurgeons ?? []).map(\.initials),
      mySchedule: scheduleItems,
      meetings: meetingItems,
      personalItems: personal,
      hasMyApprovedOff: allItems.contains { $0.type == "dayoff" },
      hasClinicOr: allItems.contains { $0.type == "clinic" || $0.type == "surgery" },
      hasBlockTime: allItems.contains { $0.type == "block_or" },
      hasMeeting: allItems.contains { $0.type == "meeting" }
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

    let procedure = (subtitle ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let loc = (location ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let roomValue = (room ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    return DoctorScheduleItem(
      id: id ?? "\(dateKey)-\(rawId ?? 0)-\(title)",
      period: periodLabel,
      title: displayTitle,
      subtitle: [loc, roomValue, procedure].filter { !$0.isEmpty }.joined(separator: " · "),
      timeRange: timeRange,
      kind: type,
      location: loc,
      room: roomValue,
      procedure: procedure,
      notes: (notes ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
      start: start ?? "",
      end: end ?? ""
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
      timeRange: timeRange,
      kind: "meeting",
      location: (location ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
      room: (room ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
      procedure: (subtitle ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
      notes: (notes ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
      start: start ?? "",
      end: end ?? ""
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
    case "block_or":
      return title.isEmpty ? "Block OR" : title
    default:
      return title
    }
  }

  private var periodLabel: String {
    // Timed clinic-day rows (e.g. Surgery 1 / CBO) keep AM/PM from start time.
    // Session-based clinic rows already carry AM/PM/FULL in subtitle.
    if type == "clinic", let subtitle, ["AM", "PM", "FULL"].contains(subtitle.uppercased()) {
      return subtitle.uppercased()
    }
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
    return "\(String(format: "%02d", hour24)):\(minute)"
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
  let coverageId: Int?

  func scheduleAssignment(dateKey: String) -> ScheduleAssignment {
    let displayedInitials = coveringInitials ?? initials ?? surgeonInitials(from: surgeon)
    return ScheduleAssignment(
      id: "\(dateKey)-\(rotationId)",
      rotationId: rotationId,
      coverageId: coverageId,
      location: group,
      locationShort: shortGroupName(group),
      surgeon: displayedInitials,
      surgeonId: surgeonId,
      originalInitials: originalInitials ?? initials ?? surgeonInitials(from: surgeon),
      originalSurgeonId: originalSurgeonId ?? surgeonId,
      coveringInitials: coveringInitials,
      coveringSurgeonId: coveringSurgeonId,
      isCovered: isCovered == true,
      time: "07:00 - 17:00",
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
