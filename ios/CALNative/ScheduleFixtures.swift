import Foundation

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
