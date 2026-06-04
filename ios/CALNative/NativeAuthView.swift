import SwiftUI

struct NativeAuthView: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var email = ""
  @State private var code = ""
  @State private var hasRequestedCode = false

  var body: some View {
    NavigationView {
      Form {
        Section {
          TextField("Email", text: $email)
            .keyboardType(.emailAddress)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()

          if hasRequestedCode {
            TextField("Code", text: $code)
              .keyboardType(.numberPad)
          }
        } header: {
          Text("Sign In")
        } footer: {
          Text("Use the same one-time code login as CAL on the web.")
        }

        Section {
          Button(action: submit) {
            HStack {
              Text(hasRequestedCode ? "Verify Code" : "Send Code")
              Spacer()
              if store.authBusy {
                ProgressView()
              }
            }
          }
          .disabled(isSubmitDisabled)
        }

        if let message = store.authMessage {
          Section {
            Text(message)
              .font(.subheadline)
              .foregroundStyle(.secondary)
          }
        }
      }
      .navigationTitle("CAL")
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
