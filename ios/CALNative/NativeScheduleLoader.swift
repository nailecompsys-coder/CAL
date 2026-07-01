import Foundation

struct NativeScheduleSnapshot {
  let currentSurgeon: NativeSurgeon?
  let surgeons: [NativeSurgeon]
  let days: [ScheduleDay]
  let timeOffRequests: [TimeOffRequest]
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

  func loadLookahead(token: String, containing date: Date, daysAhead: Int = 30) async throws -> NativeScheduleSnapshot {
    let calendar = Calendar.current
    let start = calendar.startOfDay(for: date)
    let end = calendar.date(byAdding: .day, value: daysAhead, to: start) ?? start
    return try await load(token: token, start: start, end: end)
  }

  private func load(token: String, start: Date, end: Date) async throws -> NativeScheduleSnapshot {
    let home = try await client.fetchHome(token: token, start: start, end: end)
    return NativeScheduleSnapshot(
      currentSurgeon: home.surgeon,
      surgeons: home.surgeons ?? [],
      days: home.days.map(\.scheduleDay),
      timeOffRequests: home.requests.map(\.timeOffRequest)
    )
  }
}
