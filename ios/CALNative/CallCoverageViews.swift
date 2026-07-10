import SwiftUI

struct StruckInitialsText: View {
  let text: String
  let font: Font

  var body: some View {
    Text(text)
      .font(font)
      .foregroundStyle(.red)
      .overlay(alignment: .center) {
        Rectangle()
          .fill(.red)
          .frame(height: 1.4)
      }
  }
}

struct CallCoverageSheet: View {
  let assignment: ScheduleAssignment
  let currentSurgeon: NativeSurgeon?
  let surgeons: [NativeSurgeon]
  let isSaving: Bool
  let saveAction: (NativeSurgeon) -> Void
  let cancelAction: () -> Void

  @State private var selectedSurgeonId: Int?

  private var selectedSurgeon: NativeSurgeon? {
    surgeons.first { $0.id == selectedSurgeonId }
  }

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        VStack(alignment: .leading, spacing: 12) {
          VStack(alignment: .leading, spacing: 6) {
            Text(assignment.locationShort)
              .font(.headline.weight(.semibold))
            HStack(spacing: 6) {
              if assignment.isCovered {
                StruckInitialsText(
                  text: assignment.originalInitials,
                  font: .system(.title3, design: .monospaced).weight(.bold)
                )
              } else {
                Text(assignment.originalInitials)
                  .font(.system(.title3, design: .monospaced).weight(.bold))
                  .foregroundStyle(.red)
              }
              Image(systemName: "arrow.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(.secondary)
              Text(selectedSurgeon?.initials ?? "—")
                .font(.system(.title3, design: .monospaced).weight(.bold))
                .foregroundStyle(selectedSurgeon == nil ? .secondary : .primary)
            }
            if selectedSurgeon == nil {
              Text("Select covering surgeon")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            }
          }
          .padding(14)
          .frame(maxWidth: .infinity, alignment: .leading)
          .liquidGlassCard(cornerRadius: 18, tint: ClinicalPalette.cardStrong)

          if surgeons.isEmpty {
            EmptyDashboardRow(title: "No eligible covering surgeons loaded")
              .padding(14)
              .liquidGlassCard(cornerRadius: 16, tint: ClinicalPalette.amber)
          } else {
            ScrollView {
              VStack(spacing: 8) {
                ForEach(surgeons) { surgeon in
                  Button {
                    selectedSurgeonId = surgeon.id
                  } label: {
                    HStack(spacing: 10) {
                      Text(surgeon.initials)
                        .font(.system(.subheadline, design: .monospaced).weight(.bold))
                        .foregroundStyle(ClinicalPalette.teal)
                        .frame(width: 42, alignment: .leading)

                      VStack(alignment: .leading, spacing: 2) {
                        Text(surgeon.name)
                          .font(.subheadline.weight(.semibold))
                          .foregroundStyle(.primary)
                        Text(surgeon.staffType == "physician" ? "Surgeon" : "PA / Staff")
                          .font(.caption2)
                          .foregroundStyle(.secondary)
                      }

                      Spacer()

                      if selectedSurgeonId == surgeon.id {
                        Image(systemName: "checkmark.circle.fill")
                          .foregroundStyle(ClinicalPalette.teal)
                      }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .liquidGlassCard(
                      cornerRadius: 15,
                      tint: selectedSurgeonId == surgeon.id ? ClinicalPalette.tealSoft : Color.white.opacity(0.62)
                    )
                  }
                  .buttonStyle(.plain)
                }
              }
            }
          }

          Button {
            if let selectedSurgeon {
              saveAction(selectedSurgeon)
            }
          } label: {
            HStack {
              Spacer()
              if isSaving {
                ProgressView()
              } else {
                Text("Save Coverage")
                  .font(.subheadline.weight(.semibold))
              }
              Spacer()
            }
            .padding(.vertical, 12)
            .background(
              (selectedSurgeon == nil || isSaving ? ClinicalPalette.muted : ClinicalPalette.teal),
              in: RoundedRectangle(cornerRadius: 14)
            )
            .foregroundStyle(.white)
          }
          .disabled(selectedSurgeon == nil || isSaving)
        }
        .padding(16)
      }
      .navigationTitle("Cover On Call")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel", action: cancelAction)
        }
      }
    }
    .onAppear {
      // Safety: never pre-select a covering surgeon (avoids accidental save).
      selectedSurgeonId = nil
    }
  }
}
