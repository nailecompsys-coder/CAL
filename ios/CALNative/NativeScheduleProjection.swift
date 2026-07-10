import Foundation

struct NativeScheduleProjection {
  let days: [ScheduleDay]

  func day(for date: Date) -> ScheduleDay? {
    let key = dateKey(date)
    return days.first { $0.id == key }
  }

  func week(containing date: Date) -> [ScheduleDay] {
    let calendar = Calendar.current
    let interval = calendar.dateInterval(of: .weekOfYear, for: date)
    let start = interval?.start ?? calendar.startOfDay(for: date)

    return (0..<7).compactMap { offset in
      guard let dayDate = calendar.date(byAdding: .day, value: offset, to: start) else { return nil }
      return day(for: dayDate) ?? ScheduleDay.empty(for: dayDate)
    }
  }

  func month(containing date: Date) -> [MonthCell] {
    let calendar = Calendar.current
    guard let monthInterval = calendar.dateInterval(of: .month, for: date) else { return [] }

    let firstOfMonth = monthInterval.start
    let leadingDays = calendar.component(.weekday, from: firstOfMonth) - 1
    let gridStart = calendar.date(byAdding: .day, value: -leadingDays, to: firstOfMonth) ?? firstOfMonth

    return (0..<42).compactMap { offset in
      guard let cellDate = calendar.date(byAdding: .day, value: offset, to: gridStart) else { return nil }
      let isCurrentMonth = calendar.isDate(cellDate, equalTo: date, toGranularity: .month)
      let isToday = calendar.isDateInToday(cellDate)
      guard let day = self.day(for: cellDate) else {
        return MonthCell.empty(for: cellDate, isCurrentMonth: isCurrentMonth, isToday: isToday)
      }
      return MonthCell(
        id: dateKey(cellDate),
        date: cellDate,
        isCurrentMonth: isCurrentMonth,
        isToday: isToday,
        assignments: day.assignments,
        callInitials: day.assignments.map(\.surgeon),
        offInitials: day.off,
        schedulePeriods: day.mySchedule.map(\.period),
        hasMyApprovedOff: day.hasMyApprovedOff,
        hasClinicOr: day.hasClinicOr,
        hasBlockTime: day.hasBlockTime,
        hasMeeting: day.hasMeeting
      )
    }
  }
}
