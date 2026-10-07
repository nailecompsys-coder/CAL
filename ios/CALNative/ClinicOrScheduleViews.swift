import SwiftUI

enum ClinicOrScheduleBuilder {
  /// Facility headers (clinic / OR / Surgery One…) with nested cases or clinic visits.
  /// Block OR is the hospital time window — it still shows when no case is booked yet.
  /// Aprima Surgery One / IPA + hospital outpt (AHWG → Winter Garden OR) nest here too.
  static func groups(from items: [DoctorScheduleItem]) -> [ClinicOrFacilityGroup] {
    let clinics = items.filter { $0.kind == "clinic" }
    let surgeries = items.filter { $0.kind == "surgery" }
    let blocks = items.filter { $0.isBlockOr }
    var claimed = Set<String>()
    var claimedBlocks = Set<String>()
    var groups: [ClinicOrFacilityGroup] = []

    var matchedByClinic: [String: [DoctorScheduleItem]] = [:]
    for clinic in clinics where !isEmptyCard(clinic) {
      let matched = surgeries.filter { surgeryBelongs($0, to: clinic) }
      matched.forEach { claimed.insert($0.id) }
      matchedByClinic[clinic.id] = matched
    }
    // A case on an OFF / NA half-day is listed under that card (flagged), not as a separate row.
    for clinic in clinics where isEmptyCard(clinic) {
      let matched = surgeries.filter { !claimed.contains($0.id) && $0.period == clinic.period }
      matched.forEach { claimed.insert($0.id) }
      matchedByClinic[clinic.id] = matched
    }

    for clinic in clinics {
      let matched = matchedByClinic[clinic.id] ?? []
      if isEmptyCard(clinic) {
        groups.append(
          ClinicOrFacilityGroup(
            id: clinic.id,
            period: clinic.period,
            title: clinic.title,
            details: matched.sorted { $0.start < $1.start }.map { surgeryDetail($0, showsLocation: true) },
            countStyle: .cases
          )
        )
        continue
      }
      let isOR = looksLikeOperatingRoom(clinic.title)
      let matchingBlock = blocks.first { blockMatchesFacility($0, clinic.title) }
      if let matchingBlock {
        claimedBlocks.insert(matchingBlock.id)
      }

      let details: [ClinicOrDetailRow]
      if isOR {
        details = matched
          .sorted { $0.start < $1.start }
          .map { surgeryDetail($0) }
      } else if !matched.isEmpty {
        let fromAprima = matched.sorted { $0.start < $1.start }.map { surgeryDetail($0) }
        let fromNotes = parseClinicVisits(from: clinic.notes)
        details = mergeDetails(fromAprima, fromNotes)
      } else {
        details = parseClinicVisits(from: clinic.notes)
      }

      groups.append(
        ClinicOrFacilityGroup(
          id: clinic.id,
          period: clinic.period,
          title: clinic.title,
          details: details,
          countStyle: isOR ? .cases : .visits
        )
      )
    }

    let leftover = surgeries.filter { !claimed.contains($0.id) }
    let byLocation = Dictionary(grouping: leftover) { locationKey(for: $0) }
    for key in byLocation.keys.sorted() {
      guard let cases = byLocation[key], !cases.isEmpty else { continue }
      let sorted = cases.sorted { $0.start < $1.start }
      let isOR = looksLikeOperatingRoom(key)
      let matchingBlock = blocks.first { blockMatchesFacility($0, key) }
      if let matchingBlock {
        claimedBlocks.insert(matchingBlock.id)
      }
      groups.append(
        ClinicOrFacilityGroup(
          id: "loc-\(key)",
          period: matchingBlock?.period ?? sorted.first?.period ?? "",
          title: displayFacilityTitle(key),
          details: sorted.map { surgeryDetail($0) },
          countStyle: isOR ? .cases : .visits
        )
      )
    }

    for block in blocks where !claimedBlocks.contains(block.id) {
      let title = displayFacilityTitle(blockFacilityName(block))
      if groups.contains(where: { facilityKey($0.title) == facilityKey(title) }) {
        continue
      }
      groups.append(
        ClinicOrFacilityGroup(
          id: block.id,
          period: block.period,
          title: title,
          details: [],
          countStyle: .cases
        )
      )
    }

    let periodRank = ["AM": 0, "PM": 1]
    return groups.enumerated()
      .sorted { (periodRank[$0.element.period] ?? 2, $0.offset) < (periodRank[$1.element.period] ?? 2, $1.offset) }
      .map(\.element)
  }

  private static func isEmptyCard(_ item: DoctorScheduleItem) -> Bool {
    ["OFF", "NA"].contains(item.title.uppercased())
  }

  private static func blockFacilityName(_ block: DoctorScheduleItem) -> String {
    let loc = block.location.trimmingCharacters(in: .whitespacesAndNewlines)
    if !loc.isEmpty { return loc }
    return block.title
  }

  private static func facilityKey(_ value: String) -> String {
    canonicalFacility(normalizeFacility(value))
  }

  private static func blockMatchesFacility(_ block: DoctorScheduleItem, _ facility: String) -> Bool {
    let blockKey = facilityKey(blockFacilityName(block))
    let other = facilityKey(facility)
    return !blockKey.isEmpty && blockKey == other
  }

  private static func surgeryBelongs(_ surgery: DoctorScheduleItem, to clinic: DoctorScheduleItem) -> Bool {
    let loc = surgery.location.trimmingCharacters(in: .whitespacesAndNewlines)
    let title = clinic.title.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !title.isEmpty else { return false }

    if !loc.isEmpty {
      if loc.caseInsensitiveCompare(title) == .orderedSame {
        return true
      }
      let locNorm = normalizeFacility(loc)
      let titleNorm = normalizeFacility(title)
      if locNorm == titleNorm || locNorm.contains(titleNorm) || titleNorm.contains(locNorm) {
        return true
      }
      if canonicalFacility(locNorm) == canonicalFacility(titleNorm) {
        return true
      }
    }

    // Pre-mapping builds may still carry Aprima site on room.
    let room = surgery.room.trimmingCharacters(in: .whitespacesAndNewlines)
    if !room.isEmpty {
      let roomCanon = canonicalFacility(normalizeFacility(room))
      let titleCanon = canonicalFacility(normalizeFacility(title))
      if !roomCanon.isEmpty, roomCanon == titleCanon {
        return true
      }
    }
    return false
  }

  private static func surgeryDetail(_ item: DoctorScheduleItem, showsLocation: Bool = false) -> ClinicOrDetailRow {
    let procedure = item.procedure.trimmingCharacters(in: .whitespacesAndNewlines)
    let room = item.room.trimmingCharacters(in: .whitespacesAndNewlines)
    let location = showsLocation ? locationKey(for: item) : ""
    let reviewLabel = item.needsReview && !showsLocation ? "Aprima review" : ""
    let secondary = [reviewLabel, location, procedure, room == location ? "" : room]
      .filter { !$0.isEmpty }
      .joined(separator: " · ")
    return ClinicOrDetailRow(
      id: item.id,
      time: displayClock(item.start),
      primary: item.title,
      secondary: secondary,
      isReviewWarning: item.needsReview
    )
  }

  private static func mergeDetails(_ primary: [ClinicOrDetailRow], _ secondary: [ClinicOrDetailRow]) -> [ClinicOrDetailRow] {
    var seen = Set(primary.map { "\($0.time)|\($0.primary.lowercased())" })
    var out = primary
    for row in secondary {
      let key = "\(row.time)|\(row.primary.lowercased())"
      if seen.insert(key).inserted {
        out.append(row)
      }
    }
    return out.sorted { $0.time < $1.time }
  }

  private static func parseClinicVisits(from notes: String) -> [ClinicOrDetailRow] {
    guard !notes.isEmpty else { return [] }
    let pattern = #"(\d{1,2}:\d{2})\s+([^;]+)"#
    guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
    let ns = notes as NSString
    let matches = regex.matches(in: notes, range: NSRange(location: 0, length: ns.length))
    var rows: [ClinicOrDetailRow] = []
    for match in matches {
      guard match.numberOfRanges >= 3,
            let timeRange = Range(match.range(at: 1), in: notes),
            let nameRange = Range(match.range(at: 2), in: notes) else {
        continue
      }
      let time = String(notes[timeRange])
      let name = String(notes[nameRange])
        .trimmingCharacters(in: .whitespacesAndNewlines)
      if name.isEmpty { continue }
      let lower = name.lowercased()
      if lower.contains("desk fax") || lower.contains("kno2") || lower.hasPrefix("source=") {
        continue
      }
      rows.append(
        ClinicOrDetailRow(
          id: "visit-\(time)-\(name)",
          time: displayClock(time),
          primary: name,
          secondary: ""
        )
      )
    }
    return rows
  }

  private static func locationKey(for item: DoctorScheduleItem) -> String {
    let loc = item.location.trimmingCharacters(in: .whitespacesAndNewlines)
    if !loc.isEmpty {
      return displayFacilityTitle(loc)
    }
    let room = item.room.trimmingCharacters(in: .whitespacesAndNewlines)
    if !room.isEmpty {
      return displayFacilityTitle(room)
    }
    return "Surgery"
  }

  private static func displayFacilityTitle(_ value: String) -> String {
    let canon = canonicalFacility(normalizeFacility(value))
    switch canon {
    case "winter garden or": return "Winter Garden OR"
    case "apopka or": return "Apopka OR"
    case "altamonte or": return "Altamonte OR"
    case "minneola or": return "Minneola OR"
    case "winter garden clinic": return "Winter Garden Clinic"
    case "apopka clinic": return "Apopka Clinic"
    case "surgery one": return "Surgery One"
    default: return value
    }
  }

  private static func normalizeFacility(_ value: String) -> String {
    value
      .lowercased()
      .replacingOccurrences(of: "-", with: " ")
      .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
      .trimmingCharacters(in: .whitespacesAndNewlines)
  }

  /// Collapse Aprima site codes and CAL names onto one key for matching.
  private static func canonicalFacility(_ normalized: String) -> String {
    let compact = normalized.replacingOccurrences(of: " ", with: "")
    if compact.contains("ahwg") || compact == "wgd" || compact == "wgor" || compact.contains("wintergardenor") {
      return "winter garden or"
    }
    if compact.contains("ahapop") || compact.contains("apk") || compact == "apor" || compact.contains("apopkaor") {
      return "apopka or"
    }
    if compact.contains("ahalt") || compact == "alor" || compact.contains("altamonteor") {
      return "altamonte or"
    }
    if compact.contains("ahmin") || compact == "mnor" || compact.contains("minneolaor") {
      return "minneola or"
    }
    if compact.contains("clermont") || compact.contains("mainoffice") || compact.contains("mainclinic")
        || compact.contains("surgeryone") || normalized == "surgery one" {
      return "surgery one"
    }
    if normalized.contains("winter garden") && normalized.contains("clinic") {
      return "winter garden clinic"
    }
    if normalized.contains("winter garden") && normalized.contains("or") {
      return "winter garden or"
    }
    if normalized.contains("apopka") && normalized.contains("clinic") {
      return "apopka clinic"
    }
    if normalized.contains("apopka") && normalized.contains("or") {
      return "apopka or"
    }
    return normalized
  }

  private static func looksLikeOperatingRoom(_ title: String) -> Bool {
    let t = title.lowercased()
    if t.contains("clinic") || t.contains("surgery one") { return false }
    let canon = canonicalFacility(normalizeFacility(title))
    if canon == "surgery one" { return false }
    if canon.hasSuffix(" or") { return true }
    return t.hasSuffix(" or")
      || t.contains("-or")
      || t.hasPrefix("surgery ")
  }

  private static func displayClock(_ value: String) -> String {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return "" }
    let parts = trimmed.split(separator: ":")
    guard let hourText = parts.first, let hour = Int(hourText) else {
      return trimmed
    }
    let minute = parts.count > 1 ? String(parts[1].prefix(2)) : "00"
    return "\(String(format: "%02d", hour)):\(minute)"
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
