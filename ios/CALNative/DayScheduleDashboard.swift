import SwiftUI

struct DayScheduleDashboard: View {
  let day: ScheduleDay
  let days: [ScheduleDay]
  let statusMessage: String?
  let coverAction: (ScheduleAssignment) -> Void

  private var orderedDays: [ScheduleDay] {
    var byId = Dictionary(uniqueKeysWithValues: days.map { ($0.id, $0) })
    byId[day.id] = day
    return byId.values.sorted { $0.date < $1.date }
  }

  private var nextMeeting: (date: Date, content: String)? {
    nextAgendaItem { day in
      day.meetings.first.map(Self.meetingSummary)
    }
  }

  private var nextPersonal: (date: Date, content: String)? {
    nextAgendaItem { day in
      day.personalItems.first
    }
  }

  private func nextAgendaItem(_ contentForDay: (ScheduleDay) -> String?) -> (date: Date, content: String)? {
    let calendar = Calendar.current
    let start = calendar.startOfDay(for: day.date)
    let end = calendar.date(byAdding: .day, value: 30, to: start) ?? start

    for candidate in orderedDays {
      let candidateDate = calendar.startOfDay(for: candidate.date)
      guard candidateDate > start, candidateDate <= end else {
        continue
      }

      if let content = contentForDay(candidate), !content.isEmpty {
        return (candidate.date, content)
      }
    }

    return nil
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 8) {
        if let statusMessage {
          Label(statusMessage, systemImage: "exclamationmark.triangle")
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
        }

        ScheduleDailyGlanceCard(day: day, coverAction: coverAction)

        DashboardSection(title: "Clinic / OR Schedule", tint: ClinicalPalette.cardStrong) {
          ClinicOrScheduleList(dayId: day.id, items: day.mySchedule)
        }

        DashboardSection(title: "Meetings", tint: ClinicalPalette.meeting) {
          AgendaPreviewRows(
            todayContent: day.meetings.isEmpty ? nil : day.meetings.map(Self.meetingSummary).joined(separator: ", "),
            emptyTodayText: "none",
            nextDate: nextMeeting?.date,
            nextContent: nextMeeting?.content,
            systemImage: "person.2"
          )
        }

        DashboardSection(title: "Personal", tint: ClinicalPalette.mint) {
          AgendaPreviewRows(
            todayContent: day.personalItems.isEmpty ? nil : day.personalItems.joined(separator: ", "),
            emptyTodayText: "none",
            nextDate: nextPersonal?.date,
            nextContent: nextPersonal?.content,
            systemImage: "note.text"
          )
        }
      }
      .padding(.horizontal, 16)
      .padding(.top, 4)
      .padding(.bottom, 18)
    }
  }

  private static func meetingSummary(_ item: DoctorScheduleItem) -> String {
    [item.timeRange, item.title, item.subtitle]
      .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
      .joined(separator: " ")
  }
}

private struct AgendaPreviewRows: View {
  let todayContent: String?
  let emptyTodayText: String
  let nextDate: Date?
  let nextContent: String?
  let systemImage: String

  var body: some View {
    VStack(alignment: .leading, spacing: 5) {
      AgendaPreviewRow(
        prefix: "Today:",
        content: todayContent ?? emptyTodayText,
        systemImage: systemImage,
        isMuted: todayContent == nil
      )

      if let nextDate, let nextContent, !nextContent.isEmpty {
        AgendaPreviewRow(
          prefix: nextDate.formatted(.dateTime.month(.defaultDigits).day()),
          content: nextContent,
          systemImage: "calendar",
          isMuted: false
        )
      }
    }
  }
}

private struct AgendaPreviewRow: View {
  let prefix: String
  let content: String
  let systemImage: String
  let isMuted: Bool

  var body: some View {
    Label {
      HStack(alignment: .firstTextBaseline, spacing: 4) {
        Text(prefix)
          .fontWeight(.semibold)
          .foregroundStyle(isMuted ? ClinicalPalette.muted : ClinicalPalette.ink)
        Text(content)
          .foregroundStyle(isMuted ? ClinicalPalette.muted : ClinicalPalette.ink)
          .lineLimit(2)
          .fixedSize(horizontal: false, vertical: true)
      }
      .font(.caption)
    } icon: {
      Image(systemName: systemImage)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(ClinicalPalette.teal)
    }
  }
}
