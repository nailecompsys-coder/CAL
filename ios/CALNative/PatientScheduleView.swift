import SwiftUI

struct PatientScheduleView: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var selectedSection: CALNativeSection
  @State private var selectedDate = Date()

  private var groupedAppointments: [(Date, [String: [PatientAppointment]])] {
    let byDay = Dictionary(grouping: store.patientAppointments) { appointment in
      Calendar.current.startOfDay(for: appointment.date)
    }

    return byDay.keys.sorted().map { day in
      let bySurgeon = Dictionary(grouping: byDay[day] ?? []) { appointment in
        appointment.surgeonName.isEmpty ? "Unassigned" : appointment.surgeonName
      }
      return (day, bySurgeon)
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

            if store.isLoading && store.patientAppointments.isEmpty {
              ProgressView("Loading Aprima schedule...")
                .frame(maxWidth: .infinity)
                .padding(.vertical, 30)
            } else if groupedAppointments.isEmpty {
              EmptyPatientScheduleCard()
            } else {
              ForEach(groupedAppointments, id: \.0) { day, surgeonGroups in
                PatientDayCard(day: day, surgeonGroups: surgeonGroups)
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
        Text("Aprima Schedule")
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
    Label("No Aprima appointments in this range", systemImage: "calendar.badge.checkmark")
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
  let surgeonGroups: [String: [PatientAppointment]]

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text(day.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()))
        .font(.subheadline.weight(.semibold))
        .foregroundStyle(ClinicalPalette.ink)

      ForEach(surgeonGroups.keys.sorted(), id: \.self) { surgeon in
        if let appointments = surgeonGroups[surgeon] {
          PatientSurgeonBlock(surgeon: surgeon, appointments: appointments)
        }
      }
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 10)
    .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.cardStrong)
  }
}

private struct PatientSurgeonBlock: View {
  let surgeon: String
  let appointments: [PatientAppointment]

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack(spacing: 7) {
        Text(appointments.first?.surgeonInitials ?? "")
          .font(.caption.weight(.bold))
          .foregroundStyle(.white)
          .frame(width: 34, height: 22)
          .background(Capsule().fill(ClinicalPalette.teal))

        Text(surgeon)
          .font(.footnote.weight(.semibold))
          .foregroundStyle(ClinicalPalette.ink)

        Spacer()

        Text("\(appointments.count)")
          .font(.caption.weight(.semibold))
          .foregroundStyle(ClinicalPalette.muted)
      }

      ForEach(appointments.sorted { ($0.start, $0.patientName) < ($1.start, $1.patientName) }) { appointment in
        PatientAppointmentRow(appointment: appointment)
      }
    }
    .padding(.top, 2)
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
      appointment.status,
      appointment.reason,
      appointment.locationLine
    ]
      .filter { !$0.isEmpty }
      .joined(separator: " · ")
  }
}
