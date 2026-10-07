import SwiftUI

enum ClinicOrScheduleBuilder {
  /// One row per master card (AM / PM) with the cases SQL attached to it by card id.
  /// Rows without a card (weekend cases, Aprima review rows) are listed by half-day and location.
  static func groups(from items: [DoctorScheduleItem]) -> [ClinicOrFacilityGroup] {
    let cards = items.filter(\.isCard)
    let cases = items.filter { !$0.isCard }
    let cardIds = Set(cards.compactMap(\.cardId))
    var groups: [ClinicOrFacilityGroup] = cards.map { card in
      let attached = cases.filter { $0.cardId != nil && $0.cardId == card.cardId }.sorted { $0.start < $1.start }
      let emptyCard = isEmptyCard(card)
      return ClinicOrFacilityGroup(
        id: card.id,
        period: card.period,
        title: card.title,
        details: attached.map { detail($0, showsLocation: emptyCard) },
        countStyle: emptyCard || card.isBlockOr ? .cases : .visits,
        bookedCount: card.isBlockOr || emptyCard ? card.caseCount : card.visitCount
      )
    }

    let unattached = cases.filter { $0.cardId == nil || !cardIds.contains($0.cardId!) }
    let byPeriodLocation = Dictionary(grouping: unattached) { "\($0.period)|\(locationTitle($0))" }
    for key in byPeriodLocation.keys.sorted() {
      guard let rows = byPeriodLocation[key], let first = rows.first else { continue }
      groups.append(
        ClinicOrFacilityGroup(
          id: "loc-\(key)",
          period: first.period,
          title: locationTitle(first),
          details: rows.sorted { $0.start < $1.start }.map { detail($0, showsLocation: false) },
          countStyle: .cases
        )
      )
    }

    let periodRank = ["AM": 0, "PM": 1]
    return groups.enumerated()
      .sorted { (periodRank[$0.element.period] ?? 2, $0.offset) < (periodRank[$1.element.period] ?? 2, $1.offset) }
      .map(\.element)
  }

  /// Month-cell letters per half-day, AM before PM: O = OR, C = clinic, M = meeting.
  /// Read straight from the master cards' SQL counts: zero is muted, one or more is bold.
  static func periodCodes(items: [DoctorScheduleItem], meetings: [DoctorScheduleItem]) -> (am: [PeriodCode], pm: [PeriodCode]) {
    var codes: [String: [PeriodCode]] = ["AM": [], "PM": []]
    func add(_ letter: String, _ period: String, active: Bool) {
      guard var list = codes[period] else { return }
      if let index = list.firstIndex(where: { $0.letter == letter }) {
        list[index].isActive = list[index].isActive || active
      } else {
        list.append(PeriodCode(letter: letter, isActive: active))
      }
      codes[period] = list
    }
    for card in items where card.isCard {
      if isEmptyCard(card) {
        if card.caseCount > 0 { add("O", card.period, active: true) }
        if card.visitCount > 0 { add("C", card.period, active: true) }
      } else if card.isBlockOr {
        add("O", card.period, active: card.caseCount > 0)
      } else {
        add("C", card.period, active: card.visitCount > 0 || card.caseCount > 0)
      }
    }
    for meeting in meetings {
      add("M", meeting.start.isEmpty || meeting.start < "12:00" ? "AM" : "PM", active: true)
    }
    return (codes["AM"] ?? [], codes["PM"] ?? [])
  }

  private static func isEmptyCard(_ item: DoctorScheduleItem) -> Bool {
    ["OFF", "NA"].contains(item.title.uppercased())
  }

  private static func locationTitle(_ item: DoctorScheduleItem) -> String {
    let location = item.location.trimmingCharacters(in: .whitespacesAndNewlines)
    return location.isEmpty ? "Surgery" : location
  }

  private static func detail(_ item: DoctorScheduleItem, showsLocation: Bool) -> ClinicOrDetailRow {
    let procedure = item.procedure.trimmingCharacters(in: .whitespacesAndNewlines)
    let room = item.room.trimmingCharacters(in: .whitespacesAndNewlines)
    let location = showsLocation ? locationTitle(item) : ""
    let reviewLabel = item.needsReview && item.source == "aprima" ? "Aprima review" : ""
    let secondary = [reviewLabel, location, procedure, room == location ? "" : room]
      .filter { !$0.isEmpty }
      .joined(separator: " · ")
    return ClinicOrDetailRow(
      id: item.id,
      time: String(item.start.prefix(5)),
      primary: item.title,
      secondary: secondary,
      isReviewWarning: item.needsReview
    )
  }
}

struct ClinicOrScheduleList: View {
  let dayId: String
  let items: [DoctorScheduleItem]

  private var groups: [ClinicOrFacilityGroup] {
    ClinicOrScheduleBuilder.groups(from: items)
  }

  /// IDs the user has collapsed; everything else stays open by default.
  @State private var collapsedIds: Set<String> = []

  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      if groups.isEmpty {
        EmptyDashboardRow(title: "No clinic or hospital schedule")
      } else {
        ForEach(Array(groups.enumerated()), id: \.element.id) { index, group in
          if index > 0 { Divider().padding(.vertical, 4) }
          ClinicOrFacilityBlock(
            group: group,
            isExpanded: expansionBinding(for: group.id)
          )
        }
      }
    }
    .id(dayId)
    .onChange(of: dayId) { _ in
      collapsedIds = []
    }
  }

  private func expansionBinding(for id: String) -> Binding<Bool> {
    Binding(
      get: { !collapsedIds.contains(id) },
      set: { isOn in
        if isOn {
          collapsedIds.remove(id)
        } else {
          collapsedIds.insert(id)
        }
      }
    )
  }
}

private struct ClinicOrFacilityBlock: View {
  let group: ClinicOrFacilityGroup
  @Binding var isExpanded: Bool
  @ScaledMetric(relativeTo: .footnote) private var labelColumn: CGFloat = 46

  private var titleColor: Color {
    group.isEmptyCard && !group.details.isEmpty ? Color.red : ClinicalPalette.ink
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Button {
        withAnimation(.easeInOut(duration: 0.18)) {
          isExpanded.toggle()
        }
      } label: {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
          Text(group.period.isEmpty ? "—" : group.period)
            .font(.footnote.weight(.bold))
            .foregroundStyle(.secondary)
            .frame(width: labelColumn, alignment: .leading)

          Text(group.title)
            .font(.body.weight(.semibold))
            .foregroundStyle(titleColor)
            .multilineTextAlignment(.leading)
            .frame(maxWidth: .infinity, alignment: .leading)

          if !group.countLabel.isEmpty {
            Text(group.countLabel)
              .font(.footnote)
              .foregroundStyle(group.isEmptyCard ? titleColor : Color.secondary)
          }

          if !group.details.isEmpty {
            Image(systemName: "chevron.down")
              .font(.caption.weight(.semibold))
              .foregroundStyle(.tertiary)
              .rotationEffect(.degrees(isExpanded ? 0 : -90))
          }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)

      if isExpanded && !group.details.isEmpty {
        VStack(alignment: .leading, spacing: 10) {
          ForEach(group.details) { row in
            ClinicOrDetailLine(row: row, labelColumn: labelColumn)
          }
        }
        .padding(.bottom, 4)
      }
    }
  }
}

private struct ClinicOrDetailLine: View {
  let row: ClinicOrDetailRow
  let labelColumn: CGFloat

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 10) {
      Text(row.time.isEmpty ? "—" : row.time)
        .font(.footnote.monospacedDigit())
        .foregroundStyle(.secondary)
        .frame(width: labelColumn, alignment: .leading)

      VStack(alignment: .leading, spacing: 2) {
        Text(row.primary)
          .font(.subheadline.weight(.medium))
          .foregroundStyle(row.isReviewWarning ? Color.red : ClinicalPalette.ink)
          .multilineTextAlignment(.leading)

        if !row.secondary.isEmpty {
          Text(row.secondary)
            .font(.caption)
            .foregroundStyle(row.isReviewWarning ? Color.red.opacity(0.82) : Color.secondary)
            .lineLimit(2)
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    }
  }
}
