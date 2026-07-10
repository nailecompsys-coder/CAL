import SwiftUI

struct PatientScheduleView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection
  @Binding var selectedDate: Date

  private var myAppointments: [PatientAppointment] {
    let me = store.currentSurgeon
    let myInitials = (me?.initials ?? "").trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
    let myName = (me?.name ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    // Server already scopes to the logged-in surgeon; keep a client safety net.
    return store.patientAppointments.filter { appointment in
      if myInitials.isEmpty && myName.isEmpty { return true }
      let initials = appointment.surgeonInitials.uppercased()
      if !myInitials.isEmpty, initials == myInitials { return true }
      let name = appointment.surgeonName.lowercased()
      if !myName.isEmpty, name == myName || name.contains(myName) || myName.contains(name) {
        return true
      }
      return false
    }
  }

  private var appointmentsByDay: [(Date, [PatientAppointment])] {
    let byDay = Dictionary(grouping: myAppointments) { appointment in
      Calendar.current.startOfDay(for: appointment.date)
    }
    return byDay.keys.sorted().map { day in
      let rows = (byDay[day] ?? []).sorted { lhs, rhs in
        if lhs.start != rhs.start { return lhs.start < rhs.start }
        return lhs.patientName < rhs.patientName
      }
      return (day, rows)
    }
  }

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        ScrollView {
          VStack(alignment: .leading, spacing: 10) {
            PatientRangeHeader(
              selectedDate: selectedDate,
              previousAction: { shiftSelection(by: -7) },
              nextAction: { shiftSelection(by: 7) }
            )

            if let statusMessage = store.warningMessage {
              Label(statusMessage, systemImage: "exclamationmark.triangle")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .liquidGlassCard(cornerRadius: 14, tint: ClinicalPalette.amber)
            }

            if store.isLoading && myAppointments.isEmpty {
              ProgressView("Loading Aprima schedule...")
                .frame(maxWidth: .infinity)
                .padding(.vertical, 30)
            } else if appointmentsByDay.isEmpty {
              EmptyPatientScheduleCard()
            } else {
              ForEach(appointmentsByDay, id: \.0) { day, appointments in
                PatientDayCard(day: day, appointments: appointments)
              }
            }
          }
          .padding(.horizontal, 16)
          .padding(.top, 10)
          .padding(.bottom, 18)
        }
      }
      .navigationTitle("Patients")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .principal) {
          CALNativeTitleMenu(selectedSection: $selectedSection, store: store)
        }

        ToolbarItemGroup(placement: .navigationBarTrailing) {
          DatePicker("Start Date", selection: $selectedDate, displayedComponents: .date)
            .labelsHidden()

          Button {
            Task {
              await store.loadPatientSchedule(containing: selectedDate)
            }
          } label: {
            Image(systemName: "arrow.clockwise")
          }
        }
      }
      .task {
        await store.loadPatientSchedule(containing: selectedDate)
      }
      .onChange(of: selectedDate) { nextDate in
        Task {
          await store.loadPatientSchedule(containing: nextDate)
        }
      }
    }
  }

  private func shiftSelection(by days: Int) {
    withAnimation(.snappy(duration: 0.2)) {
      selectedDate = Calendar.current.date(byAdding: .day, value: days, to: selectedDate) ?? selectedDate
    }
  }
}

private struct PatientRangeHeader: View {
  let selectedDate: Date
  let previousAction: () -> Void
  let nextAction: () -> Void

  private var endDate: Date {
    Calendar.current.date(byAdding: .day, value: 6, to: selectedDate) ?? selectedDate
  }

  var body: some View {
    HStack {
      Button(action: previousAction) {
        Image(systemName: "chevron.left")
      }

      VStack(alignment: .leading, spacing: 2) {
        Text("My Patients")
          .font(.headline.weight(.semibold))
        Text("\(selectedDate.formatted(.dateTime.month(.abbreviated).day())) - \(endDate.formatted(.dateTime.month(.abbreviated).day().year()))")
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      Spacer()

      Button(action: nextAction) {
        Image(systemName: "chevron.right")
      }
    }
    .buttonStyle(.borderless)
    .padding(.horizontal, 12)
    .padding(.vertical, 10)
    .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.tealSoft)
  }
}

private struct EmptyPatientScheduleCard: View {
  var body: some View {
    Label("No patients scheduled in this range", systemImage: "calendar.badge.checkmark")
      .font(.subheadline)
      .foregroundStyle(.secondary)
      .padding(.horizontal, 12)
      .padding(.vertical, 18)
      .frame(maxWidth: .infinity, alignment: .leading)
      .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.card)
  }
}

private struct PatientDayCard: View {
  let day: Date
  let appointments: [PatientAppointment]

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack {
        Text(day.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()))
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(ClinicalPalette.ink)
        Spacer()
        Text("\(appointments.count)")
          .font(.caption.weight(.bold))
          .foregroundStyle(.white)
          .frame(minWidth: 24, minHeight: 22)
          .padding(.horizontal, 6)
          .background(ClinicalPalette.teal, in: Capsule())
      }

      ForEach(appointments) { appointment in
        PatientAppointmentRow(appointment: appointment)
      }
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 10)
    .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.cardStrong)
  }
}

private struct PatientAppointmentRow: View {
  let appointment: PatientAppointment

  var body: some View {
    HStack(alignment: .top, spacing: 10) {
      Text(appointment.timeRange)
        .font(.caption.monospacedDigit().weight(.semibold))
        .foregroundStyle(ClinicalPalette.teal)
        .frame(width: 82, alignment: .leading)

      VStack(alignment: .leading, spacing: 2) {
        Text(appointment.patientName.isEmpty ? "Patient" : appointment.patientName)
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(ClinicalPalette.ink)

        Text(detailLine)
          .font(.caption)
          .foregroundStyle(ClinicalPalette.muted)
          .lineLimit(2)
      }

      Spacer(minLength: 0)
    }
    .padding(.vertical, 5)
    .padding(.horizontal, 8)
    .background(
      RoundedRectangle(cornerRadius: 10, style: .continuous)
        .fill(ClinicalPalette.porcelainChip.opacity(0.82))
    )
  }

  private var detailLine: String {
    [
      appointment.appointmentType,
      appointment.serviceSite.isEmpty ? appointment.locationLine : appointment.serviceSite,
      appointment.reason
    ]
      .filter { !$0.isEmpty }
      .joined(separator: " · ")
  }
}
