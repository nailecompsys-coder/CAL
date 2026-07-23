import SwiftUI

enum ClinicOrScheduleBuilder {
  /// Facility headers (clinic / OR / Surgery One…) with nested cases or clinic visits.
  /// Hides Block OR rows — cases nest under the matching facility instead.
  /// Aprima Surgery One / IPA + hospital outpt (AHWG → Winter Garden OR) nest here too.
  static func groups(from items: [DoctorScheduleItem]) -> [ClinicOrFacilityGroup] {
    let visible = items.filter { $0.kind != "block_or" }
    let clinics = visible.filter { $0.kind == "clinic" }
    let surgeries = visible.filter { $0.kind == "surgery" }
    var claimed = Set<String>()
    var groups: [ClinicOrFacilityGroup] = []

    for clinic in clinics {
      let matched = surgeries.filter { surgeryBelongs($0, to: clinic) }
      matched.forEach { claimed.insert($0.id) }
      let isOR = looksLikeOperatingRoom(clinic.title)

      let details: [ClinicOrDetailRow]
      if isOR {
        details = matched
          .sorted { $0.start < $1.start }
          .map(surgeryDetail(_:))
      } else if !matched.isEmpty {
        let fromAprima = matched.sorted { $0.start < $1.start }.map(surgeryDetail(_:))
        let fromNotes = parseClinicVisits(from: clinic.notes)
        details = mergeDetails(fromAprima, fromNotes)
      } else {
        details = parseClinicVisits(from: clinic.notes)
      }

      groups.append(
        ClinicOrFacilityGroup(
          id: clinic.id,
          title: clinic.title,
          timeRange: expandedTimeRange(facility: clinic, cases: matched),
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
      groups.append(
        ClinicOrFacilityGroup(
          id: "loc-\(key)",
          title: displayFacilityTitle(key),
          timeRange: timeSpan(for: sorted),
          details: sorted.map(surgeryDetail(_:)),
          countStyle: isOR ? .cases : .visits
        )
      )
    }

    return groups
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

  private static func surgeryDetail(_ item: DoctorScheduleItem) -> ClinicOrDetailRow {
    let procedure = item.procedure.trimmingCharacters(in: .whitespacesAndNewlines)
    let room = item.room.trimmingCharacters(in: .whitespacesAndNewlines)
    let secondary = [procedure, room].filter { !$0.isEmpty }.joined(separator: " · ")
    return ClinicOrDetailRow(
      id: item.id,
      time: displayClock(item.start),
      primary: item.title,
      secondary: secondary
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

  private static func expandedTimeRange(facility: DoctorScheduleItem, cases: [DoctorScheduleItem]) -> String {
    var starts = [facility.start].filter { !$0.isEmpty }
    var ends = [facility.end].filter { !$0.isEmpty }
    for item in cases {
      if !item.start.isEmpty { starts.append(item.start) }
      if !item.end.isEmpty { ends.append(item.end) }
    }
    guard let first = starts.sorted().first else {
      return facility.timeRange
    }
    let last = ends.sorted().last ?? facility.end
    if last.isEmpty {
      return displayClock(first)
    }
    // Earliest case/start through facility (or latest case) end — e.g. 07:15 - 12:00
    return "\(displayClock(first)) - \(displayClock(last))"
  }

  private static func timeSpan(for items: [DoctorScheduleItem]) -> String {
    let starts = items.map(\.start).filter { !$0.isEmpty }.sorted()
    let ends = items.map(\.end).filter { !$0.isEmpty }.sorted()
    guard let first = starts.first else { return "" }
    let startText = displayClock(first)
    if let lastEnd = ends.last, !lastEnd.isEmpty {
      return "\(startText) - \(displayClock(lastEnd))"
    }
    if let lastStart = starts.last, lastStart != first {
      return "\(startText) - \(displayClock(lastStart))"
    }
    return startText
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
    if compact.contains("ahwg") || compact == "wgd" || compact.contains("wintergardenor") {
      return "winter garden or"
    }
    if compact.contains("ahapop") || compact.contains("apk") || compact.contains("apopkaor") {
      return "apopka or"
    }
    if compact.contains("ahalt") || compact.contains("altamonteor") {
      return "altamonte or"
    }
    if compact.contains("ahmin") || compact.contains("minneolaor") {
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
    VStack(alignment: .leading, spacing: 2) {
      if groups.isEmpty {
        EmptyDashboardRow(title: "No clinic or hospital schedule")
      } else {
        ForEach(groups) { group in
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

  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      Button {
        withAnimation(.easeInOut(duration: 0.18)) {
          isExpanded.toggle()
        }
      } label: {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
          Text(group.timeRange.isEmpty ? "—" : group.timeRange)
            .font(ClinicalTypography.monoCaption)
            .foregroundStyle(ClinicalPalette.ink)
            .frame(width: 96, alignment: .leading)

          Text(group.headerTitle)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(ClinicalPalette.ink)
            .multilineTextAlignment(.leading)
            .frame(maxWidth: .infinity, alignment: .leading)

          Image(systemName: "chevron.down")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(ClinicalPalette.muted)
            .rotationEffect(.degrees(isExpanded ? 0 : -90))
        }
        .padding(.vertical, 8)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)

      if isExpanded {
        if group.details.isEmpty {
          Text("No cases or visits listed")
            .font(.caption)
            .foregroundStyle(ClinicalPalette.muted)
            .padding(.leading, 106)
            .padding(.bottom, 8)
        } else {
          VStack(alignment: .leading, spacing: 6) {
            ForEach(group.details) { row in
              ClinicOrDetailLine(row: row)
            }
          }
          .padding(.bottom, 8)
        }
      }
    }
  }
}

private struct ClinicOrDetailLine: View {
  let row: ClinicOrDetailRow

  var body: some View {
    HStack(alignment: .top, spacing: 10) {
      Text(row.time.isEmpty ? "—" : row.time)
        .font(ClinicalTypography.monoCaption)
        .foregroundStyle(ClinicalPalette.ink)
        .frame(width: 96, alignment: .leading)

      VStack(alignment: .leading, spacing: 2) {
        Text(row.primary)
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(ClinicalPalette.ink)
          .multilineTextAlignment(.leading)

        if !row.secondary.isEmpty {
          Text(row.secondary)
            .font(.caption2)
            .foregroundStyle(ClinicalPalette.muted)
            .lineLimit(1)
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    }
  }
}
