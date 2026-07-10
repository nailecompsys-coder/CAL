import SwiftUI

struct TimeOffInfoBanner: View {
  var body: some View {
    Label {
      Text("Pick a month to scan requested and approved time off before choosing your dates.")
        .font(.caption)
        .foregroundStyle(ClinicalPalette.muted)
        .fixedSize(horizontal: false, vertical: true)
    } icon: {
      Image(systemName: "info.circle.fill")
        .foregroundStyle(ClinicalPalette.teal)
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 9)
    .frame(maxWidth: .infinity, alignment: .leading)
    .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.tealSoft)
  }
}

struct MonthPillPicker: View {
  let months: [Date]
  @Binding var selectedMonth: Date
  private let columns = Array(repeating: GridItem(.flexible(), spacing: 7), count: 4)

  var body: some View {
    LazyVGrid(columns: columns, spacing: 7) {
      ForEach(months, id: \.self) { month in
        Button {
          selectedMonth = month
        } label: {
          Text(month.formatted(.dateTime.month(.abbreviated)))
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.85)
            .foregroundStyle(isSelected(month) ? .white : ClinicalPalette.teal)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 7)
            .background(isSelected(month) ? ClinicalPalette.teal : ClinicalPalette.cardStrong, in: Capsule())
            .overlay {
              Capsule()
                .stroke(ClinicalPalette.teal.opacity(isSelected(month) ? 0 : 0.24), lineWidth: 0.8)
            }
        }
        .buttonStyle(.plain)
      }
    }
    .padding(.vertical, 2)
  }

  private func isSelected(_ month: Date) -> Bool {
    Calendar.current.isDate(month, equalTo: selectedMonth, toGranularity: .month)
  }
}

// MARK: - Who’s Out Gantt

enum TimeOffBarStatus: String {
  case approved
  case pending
}

struct TimeOffGanttBar: Identifiable {
  let id: String
  let startDay: Int // 1-based day of month
  let endDay: Int
  let status: TimeOffBarStatus

  var spanDays: Int { endDay - startDay + 1 }
}

struct TimeOffGanttRow: Identifiable {
  let id: String
  let initials: String
  let name: String
  let bars: [TimeOffGanttBar]

  var hasBars: Bool { !bars.isEmpty }
}

struct TimeOffGanttModel {
  let daysInMonth: Int
  let dayNumbers: [Int]
  let rows: [TimeOffGanttRow]

  static func build(month: Date, days: [ScheduleDay], surgeons: [NativeSurgeon]) -> TimeOffGanttModel {
    let calendar = Calendar.current
    let daysInMonth = calendar.range(of: .day, in: .month, for: month)?.count ?? 0
    let dayNumbers = Array(1...max(daysInMonth, 0))

    var dayByNumber: [Int: ScheduleDay] = [:]
    for day in days {
      let n = calendar.component(.day, from: day.date)
      dayByNumber[n] = day
    }

    // status[initials][day] = approved | pending (approved wins if both)
    var statusBySurgeon: [String: [Int: TimeOffBarStatus]] = [:]
    for dayNum in dayNumbers {
      guard let day = dayByNumber[dayNum] else { continue }
      for initial in day.off {
        statusBySurgeon[initial, default: [:]][dayNum] = .approved
      }
      for initial in day.requestedOff {
        if statusBySurgeon[initial]?[dayNum] == nil {
          statusBySurgeon[initial, default: [:]][dayNum] = .pending
        }
      }
    }

    let surgeonByInitials = Dictionary(uniqueKeysWithValues: surgeons.map { ($0.initials, $0) })
    var orderedInitials: [String] = surgeons.map(\.initials)
    for key in statusBySurgeon.keys.sorted() where !orderedInitials.contains(key) {
      orderedInitials.append(key)
    }

    let rows: [TimeOffGanttRow] = orderedInitials.compactMap { initials in
      let map = statusBySurgeon[initials] ?? [:]
      let bars = coalesceBars(dayStatuses: map, daysInMonth: daysInMonth)
      let surgeon = surgeonByInitials[initials]
      // Show surgeons with bars; also show known surgeons even if empty (dimmed in UI)
      if bars.isEmpty && surgeon == nil { return nil }
      if bars.isEmpty && surgeon != nil {
        // Skip empty rows to keep phone Gantt scannable — only people who are out
        return nil
      }
      return TimeOffGanttRow(
        id: initials,
        initials: initials,
        name: surgeon?.name ?? initials,
        bars: bars
      )
    }

    return TimeOffGanttModel(daysInMonth: daysInMonth, dayNumbers: dayNumbers, rows: rows)
  }

  private static func coalesceBars(dayStatuses: [Int: TimeOffBarStatus], daysInMonth: Int) -> [TimeOffGanttBar] {
    var bars: [TimeOffGanttBar] = []
    var cursor = 1
    while cursor <= daysInMonth {
      guard let status = dayStatuses[cursor] else {
        cursor += 1
        continue
      }
      var end = cursor
      while end + 1 <= daysInMonth, dayStatuses[end + 1] == status {
        end += 1
      }
      bars.append(
        TimeOffGanttBar(
          id: "\(status.rawValue)-\(cursor)-\(end)",
          startDay: cursor,
          endDay: end,
          status: status
        )
      )
      cursor = end + 1
    }
    return bars
  }
}

struct TimeOffGanttView: View {
  let model: TimeOffGanttModel
  let selectedMonth: Date

  private let dayWidth: CGFloat = 22
  private let labelWidth: CGFloat = 44
  private let rowHeight: CGFloat = 28
  private let headerHeight: CGFloat = 22
  private let rowRule = ClinicalPalette.stroke.opacity(0.85)

  private var todayDayNumber: Int? {
    let calendar = Calendar.current
    guard calendar.isDate(selectedMonth, equalTo: Date(), toGranularity: .month) else { return nil }
    return calendar.component(.day, from: Date())
  }

  private var gridHeight: CGFloat {
    headerHeight + CGFloat(model.rows.count) * rowHeight
  }

  var body: some View {
    if model.daysInMonth == 0 {
      Text("Could not load month.")
        .font(.caption)
        .foregroundStyle(.secondary)
    } else if model.rows.isEmpty {
      Text("No requested or approved time off this month.")
        .font(.caption)
        .foregroundStyle(.secondary)
        .padding(.vertical, 6)
    } else {
      VStack(alignment: .leading, spacing: 8) {
        HStack(spacing: 10) {
          legendSwatch(ClinicalPalette.mint, label: "Approved")
          legendSwatch(ClinicalPalette.amber, label: "Pending")
        }
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)

        // Sticky name column + horizontally scrolling day grid
        HStack(alignment: .top, spacing: 0) {
          stickyNameColumn

          ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: true) {
              ZStack(alignment: .topLeading) {
                VStack(alignment: .leading, spacing: 0) {
                  dayHeaderRow
                  ForEach(Array(model.rows.enumerated()), id: \.element.id) { _, row in
                    timelineRow(row)
                  }
                }

                if let today = todayDayNumber {
                  Rectangle()
                    .fill(ClinicalPalette.teal)
                    .frame(width: 2, height: gridHeight)
                    .offset(x: CGFloat(today - 1) * dayWidth + (dayWidth / 2) - 1)
                    .allowsHitTesting(false)
                }
              }
            }
            .onAppear {
              centerOnToday(using: proxy)
            }
            .onChange(of: selectedMonth) { _ in
              centerOnToday(using: proxy)
            }
          }
        }
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
      }
    }
  }

  private var stickyNameColumn: some View {
    VStack(alignment: .leading, spacing: 0) {
      Text("MD")
        .font(.system(size: 9, weight: .bold))
        .foregroundStyle(.secondary)
        .frame(width: labelWidth, height: headerHeight, alignment: .leading)
        .overlay(alignment: .bottom) {
          Rectangle().fill(rowRule).frame(height: 0.5)
        }

      ForEach(Array(model.rows.enumerated()), id: \.element.id) { _, row in
        Text(row.initials)
          .font(.caption2.weight(.bold))
          .foregroundStyle(ClinicalPalette.ink)
          .lineLimit(1)
          .minimumScaleFactor(0.7)
          .frame(width: labelWidth, height: rowHeight, alignment: .leading)
          .overlay(alignment: .bottom) {
            Rectangle().fill(rowRule).frame(height: 0.5)
          }
      }
    }
    .padding(.trailing, 6)
    .background(ClinicalPalette.cardStrong.opacity(0.92))
  }

  private var dayHeaderRow: some View {
    HStack(spacing: 0) {
      ForEach(model.dayNumbers, id: \.self) { day in
        Text("\(day)")
          .font(.system(size: 8, weight: .semibold))
          .foregroundStyle(isToday(day) ? ClinicalPalette.teal : .secondary)
          .frame(width: dayWidth, height: headerHeight)
          .background(isToday(day) ? ClinicalPalette.tealSoft.opacity(0.55) : Color.clear)
          .overlay(alignment: .trailing) {
            Rectangle()
              .fill(rowRule.opacity(0.7))
              .frame(width: 0.5)
          }
          .id(dayScrollId(day))
      }
    }
    .overlay(alignment: .bottom) {
      Rectangle().fill(rowRule).frame(height: 0.5)
    }
  }

  private func timelineRow(_ row: TimeOffGanttRow) -> some View {
    ZStack(alignment: .leading) {
      HStack(spacing: 0) {
        ForEach(model.dayNumbers, id: \.self) { day in
          Rectangle()
            .fill(dayBackground(day))
            .frame(width: dayWidth, height: rowHeight)
            .overlay(alignment: .trailing) {
              Rectangle()
                .fill(rowRule.opacity(0.7))
                .frame(width: 0.5)
            }
        }
      }

      ForEach(row.bars) { bar in
        let x = CGFloat(bar.startDay - 1) * dayWidth + 1
        let w = CGFloat(bar.spanDays) * dayWidth - 2
        RoundedRectangle(cornerRadius: 4, style: .continuous)
          .fill(bar.status == .approved ? ClinicalPalette.mint : ClinicalPalette.amber)
          .overlay {
            RoundedRectangle(cornerRadius: 4, style: .continuous)
              .stroke(ClinicalPalette.ink.opacity(0.08), lineWidth: 0.5)
          }
          .overlay {
            Text(barLabel(bar))
              .font(.system(size: 8, weight: .bold))
              .foregroundStyle(ClinicalPalette.ink.opacity(0.85))
              .lineLimit(1)
              .minimumScaleFactor(0.6)
              .padding(.horizontal, 2)
          }
          .frame(width: max(w, 4), height: rowHeight - 8)
          .offset(x: x)
      }
    }
    .frame(width: CGFloat(model.daysInMonth) * dayWidth, height: rowHeight, alignment: .leading)
    .overlay(alignment: .bottom) {
      Rectangle().fill(rowRule).frame(height: 0.5)
    }
  }

  private func dayScrollId(_ day: Int) -> String {
    "gantt-day-\(day)"
  }

  private func centerOnToday(using proxy: ScrollViewProxy) {
    guard let today = todayDayNumber else { return }
    DispatchQueue.main.async {
      withAnimation(.easeInOut(duration: 0.25)) {
        proxy.scrollTo(dayScrollId(today), anchor: .center)
      }
    }
  }

  private func barLabel(_ bar: TimeOffGanttBar) -> String {
    if bar.spanDays > 1 {
      return "\(bar.startDay)–\(bar.endDay)"
    }
    return "\(bar.startDay)"
  }

  private func dayBackground(_ day: Int) -> Color {
    if isToday(day) {
      return ClinicalPalette.tealSoft.opacity(0.28)
    }
    if isWeekend(day) {
      return ClinicalPalette.ink.opacity(0.03)
    }
    return Color.clear
  }

  private func isToday(_ day: Int) -> Bool {
    todayDayNumber == day
  }

  private func isWeekend(_ day: Int) -> Bool {
    let calendar = Calendar.current
    guard let date = calendar.date(bySetting: .day, value: day, of: selectedMonth) else { return false }
    let weekday = calendar.component(.weekday, from: date)
    return weekday == 1 || weekday == 7
  }

  private func legendSwatch(_ color: Color, label: String) -> some View {
    HStack(spacing: 4) {
      RoundedRectangle(cornerRadius: 3, style: .continuous)
        .fill(color)
        .frame(width: 12, height: 8)
      Text(label)
    }
  }
}

struct MonthTimeOffList: View {
  let days: [ScheduleDay]

  private var visibleDays: [ScheduleDay] {
    days.filter { !$0.requestedOff.isEmpty || !$0.off.isEmpty }
  }

  var body: some View {
    if visibleDays.isEmpty {
      EmptyDashboardRow(title: "No requested or approved time off.")
    } else {
      VStack(alignment: .leading, spacing: 7) {
        ForEach(visibleDays) { day in
          MonthTimeOffDayRow(day: day)
        }
      }
    }
  }
}

private struct MonthTimeOffDayRow: View {
  let day: ScheduleDay

  var body: some View {
    VStack(alignment: .leading, spacing: 5) {
      Text(day.date.formatted(.dateTime.weekday(.abbreviated).month(.defaultDigits).day()))
        .font(.caption.weight(.semibold))
        .foregroundStyle(ClinicalPalette.ink)

      if !day.requestedOff.isEmpty {
        TimeOffStatusLine(label: "Requested", initials: day.requestedOff, tint: ClinicalPalette.amber, textColor: .orange)
      }

      if !day.off.isEmpty {
        TimeOffStatusLine(label: "Approved", initials: day.off, tint: ClinicalPalette.mint, textColor: ClinicalPalette.scrubInk)
      }
    }
    .padding(.vertical, 2)
  }
}

private struct TimeOffStatusLine: View {
  let label: String
  let initials: [String]
  let tint: Color
  let textColor: Color

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 7) {
      Text(label)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(ClinicalPalette.muted)
        .frame(width: 58, alignment: .leading)

      TimeOffInitialsPills(items: initials, tint: tint, textColor: textColor)
    }
  }
}

private struct TimeOffInitialsPills: View {
  let items: [String]
  let tint: Color
  let textColor: Color

  var body: some View {
    HStack(spacing: 5) {
      ForEach(items, id: \.self) { item in
        Text(item)
          .font(.caption2.weight(.semibold))
          .padding(.horizontal, 8)
          .padding(.vertical, 4)
          .background(tint.opacity(0.92), in: Capsule())
          .overlay {
            Capsule()
              .stroke(textColor.opacity(0.24), lineWidth: 0.75)
          }
          .foregroundStyle(textColor)
      }
    }
  }
}
