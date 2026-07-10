import SwiftUI

struct StruckInitialsText: View {
  let text: String
  var font: Font = ClinicalTypography.monoChip

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
    CalNavigation {
      ZStack {
        ScheduleWaterBackground()

        VStack(alignment: .leading, spacing: 12) {
          VStack(alignment: .leading, spacing: 6) {
            Text(assignment.locationShort)
              .font(ClinicalTypography.headline)
              .lineLimit(2)
              .minimumScaleFactor(0.85)

            if #available(iOS 16.0, *) {
              ViewThatFits(in: .horizontal) {
                coverageSummaryRow
                coverageSummaryStack
              }
            } else {
              coverageSummaryRow
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
                        .font(ClinicalTypography.monoRow)
                        .foregroundStyle(ClinicalPalette.teal)
                        .fixedSize(horizontal: true, vertical: false)

                      VStack(alignment: .leading, spacing: 2) {
                        Text(surgeon.name)
                          .font(ClinicalTypography.rowTitle)
                          .foregroundStyle(.primary)
                          .lineLimit(1)
                          .minimumScaleFactor(0.85)
                        Text(surgeon.staffType == "physician" ? "Surgeon" : "PA / Staff")
                          .font(.caption2)
                          .foregroundStyle(.secondary)
                      }

                      Spacer(minLength: 0)

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
                  .font(ClinicalTypography.rowTitle)
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
        .calReadableColumn(ClinicalLayout.contentColumn)
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
      selectedSurgeonId = nil
    }
  }

  private var coverageSummaryRow: some View {
    HStack(spacing: 6) {
      originalInitials
      Image(systemName: "arrow.right")
        .font(ClinicalTypography.caption)
        .foregroundStyle(.secondary)
      Text(selectedSurgeon?.initials ?? "—")
        .font(ClinicalTypography.monoTitle)
        .foregroundStyle(selectedSurgeon == nil ? .secondary : .primary)
    }
  }

  private var coverageSummaryStack: some View {
    VStack(alignment: .leading, spacing: 4) {
      originalInitials
      HStack(spacing: 6) {
        Image(systemName: "arrow.right")
          .font(ClinicalTypography.caption)
          .foregroundStyle(.secondary)
        Text(selectedSurgeon?.initials ?? "—")
          .font(ClinicalTypography.monoTitle)
          .foregroundStyle(selectedSurgeon == nil ? .secondary : .primary)
      }
    }
  }

  @ViewBuilder
  private var originalInitials: some View {
    if assignment.isCovered {
      StruckInitialsText(
        text: assignment.originalInitials,
        font: ClinicalTypography.monoTitle
      )
    } else {
      Text(assignment.originalInitials)
        .font(ClinicalTypography.monoTitle)
        .foregroundStyle(.red)
    }
  }
}
