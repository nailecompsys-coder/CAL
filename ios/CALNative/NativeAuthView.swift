import SwiftUI

struct NativeAuthView: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var email = ""
  @State private var code = ""
  @State private var hasRequestedCode = false

  var body: some View {
    NavigationView {
      ZStack {
        ScheduleWaterBackground()

        VStack(alignment: .leading, spacing: 14) {
          VStack(alignment: .leading, spacing: 5) {
            Text("CAL Sign In")
              .font(.title3.weight(.semibold))
              .foregroundStyle(ClinicalPalette.ink)
            Text(hasRequestedCode ? "Enter the code from your email." : "Enter your CAL email to continue.")
              .font(.subheadline)
              .foregroundStyle(.secondary)
          }

          TextField("Email address", text: $email)
            .keyboardType(.emailAddress)
            .textContentType(.emailAddress)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .submitLabel(.continue)
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(.white.opacity(0.82), in: RoundedRectangle(cornerRadius: 14, style: .continuous))

          if hasRequestedCode {
            TextField("6-digit code", text: $code)
              .keyboardType(.numberPad)
              .textContentType(.oneTimeCode)
              .submitLabel(.go)
              .padding(.horizontal, 14)
              .padding(.vertical, 12)
              .background(.white.opacity(0.82), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
          }

          Button(action: submit) {
            HStack {
              Text(hasRequestedCode ? "Sign In" : "Email Access Code")
                .fontWeight(.semibold)
              Spacer()
              if store.authBusy {
                ProgressView()
              }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity)
          }
          .buttonStyle(.borderedProminent)
          .disabled(isSubmitDisabled)

          if let message = store.authMessage {
            Text(message)
              .font(.subheadline)
              .foregroundStyle(.secondary)
              .padding(.horizontal, 14)
              .padding(.vertical, 12)
              .frame(maxWidth: .infinity, alignment: .leading)
              .background(.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
          }

          Spacer()
        }
        .padding(18)
      }
      .navigationTitle("CAL")
      .navigationBarTitleDisplayMode(.inline)
    }
  }

  private var isSubmitDisabled: Bool {
    store.authBusy ||
      email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
      (hasRequestedCode && code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
  }

  private func submit() {
    Task {
      if hasRequestedCode {
        await store.verifyOtp(email: email, code: code)
      } else {
        hasRequestedCode = await store.requestOtp(email: email)
      }
    }
  }
}
