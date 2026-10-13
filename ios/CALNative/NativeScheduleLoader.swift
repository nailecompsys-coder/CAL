import Foundation

struct NativeScheduleSnapshot {
  let currentSurgeon: NativeSurgeon?
  let surgeons: [NativeSurgeon]
  let days: [ScheduleDay]
  let timeOffRequests: [TimeOffRequest]
  /// All practice time-off rows from home `dayOffSections` (grouped requests, not per-day).
  let rosterTimeOff: [TimeOffRequest]
  let alerts: NativeAlertSummary
  let canCallBuilder: Bool
}

struct NativeScheduleLoader {
  private let client: NativeCALClient

  init(client: NativeCALClient = NativeCALClient()) {
    self.client = client
  }

  func load(token: String, containing date: Date, scope: ScheduleScope) async throws -> NativeScheduleSnapshot {
    let range = DateRange(containing: date, scope: scope)
    return try await load(token: token, start: range.start, end: range.end)
  }

  /// Day/home window around the focused civil month (any year — including Call built years ahead).
  func loadCalendarWindow(
    token: String,
    containing date: Date,
    monthsForward: Int = 1
  ) async throws -> NativeScheduleSnapshot {
    let range = Self.calendarWindow(containing: date, monthsForward: monthsForward)
    return try await load(token: token, start: range.start, end: range.end)
  }

  func loadLookahead(token: String, containing date: Date, daysAhead: Int = 30) async throws -> NativeScheduleSnapshot {
    // Time Off may pass a long daysAhead; otherwise load the focused month (+ next) wherever it is.
    if daysAhead >= 60 {
      let calendar = Calendar.current
      let start = calendar.startOfDay(for: date)
      let end = calendar.date(byAdding: .day, value: daysAhead, to: start) ?? start
      return try await load(token: token, start: start, end: end)
    }
    return try await loadCalendarWindow(token: token, containing: date, monthsForward: 1)
  }

  static func calendarWindow(containing date: Date, monthsForward: Int = 1) -> (start: Date, end: Date) {
    let calendar = Calendar.current
    let monthStart = calendar.date(from: calendar.dateComponents([.year, .month], from: date))
      ?? calendar.startOfDay(for: date)
    let forward = max(0, monthsForward)
    let endExclusive = calendar.date(byAdding: .month, value: forward + 1, to: monthStart) ?? monthStart
    let end = calendar.date(byAdding: .day, value: -1, to: endExclusive) ?? monthStart
    return (monthStart, end)
  }

  private func load(token: String, start: Date, end: Date) async throws -> NativeScheduleSnapshot {
    let home = try await client.fetchHome(token: token, start: start, end: end)
    var seen = Set<Int>()
    var roster: [TimeOffRequest] = []
    for section in home.dayOffSections {
      for req in section.requests.map(\.timeOffRequest) where seen.insert(req.id).inserted {
        roster.append(req)
      }
    }
    roster.sort {
      if $0.startDate != $1.startDate { return $0.startDate < $1.startDate }
      return $0.id < $1.id
    }
    return NativeScheduleSnapshot(
      currentSurgeon: home.surgeon,
      surgeons: home.surgeons ?? [],
      days: home.days.map(\.scheduleDay),
      timeOffRequests: home.requests.map(\.timeOffRequest),
      rosterTimeOff: roster,
      alerts: home.alerts ?? NativeAlertSummary(unreadCount: 0, recent: []),
      canCallBuilder: home.canCallBuilder ?? home.surgeon?.canCallBuilder ?? false
    )
  }
}
