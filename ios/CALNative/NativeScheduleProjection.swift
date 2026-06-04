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
      return day(for: dayDate) ?? ScheduleFixtures.day(for: dayDate)
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
      let day = self.day(for: cellDate) ?? ScheduleFixtures.day(for: cellDate)
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
}
