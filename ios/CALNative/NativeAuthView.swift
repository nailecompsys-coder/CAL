import SwiftUI

struct NativeAuthView: View {
  @ObservedObject var store: NativeScheduleStore
  @State private var email = ""
  @State private var code = ""
  @State private var loginRole: NativeSessionRole = .surgeon
  @FocusState private var focusedField: AuthField?

  enum AuthField {
    case email
    case code
  }

  var body: some View {
    NavigationView {
      ZStack {
        CALAuthBackground()

        GeometryReader { geometry in
          ScrollView(.vertical, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 12) {
              CALAuthHeader(todayText: Self.todayText)

              Color.clear
                .frame(height: max(geometry.size.height * 0.18, 96))

              CALAuthCard(
                store: store,
                email: $email,
                code: $code,
                loginRole: $loginRole,
                focusedField: $focusedField,
                requestCode: requestCode,
                signIn: signIn
              )
              .padding(14)
              .calAuthGlassSurface(cornerRadius: 18)
              .calAuthSoftShadow(prominent: true)
            }
            .padding(.horizontal, 18)
            .padding(.top, 14)
            .padding(.bottom, geometry.safeAreaInsets.bottom + 30)
            .frame(maxWidth: .infinity, minHeight: geometry.size.height, alignment: .top)
          }
        }
      }
      .navigationBarTitleDisplayMode(.inline)
      .navigationBarHidden(true)
    }
    .navigationViewStyle(.stack)
  }

  private static var todayText: String {
    Date.now.formatted(.dateTime.weekday(.abbreviated).month(.twoDigits).day(.twoDigits).year(.twoDigits))
  }

  private func requestCode() {
    Task {
      focusedField = nil
      if await store.requestOtp(email: email, role: loginRole) {
        focusedField = .code
      }
    }
  }

  private func signIn() {
    Task {
      focusedField = nil
      await store.verifyOtp(email: email, code: code, role: loginRole)
    }
  }
}

private struct CALAuthHeader: View {
  let todayText: String

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack(spacing: 10) {
        Image("CALLogo")
          .resizable()
          .scaledToFill()
          .frame(width: 34, height: 34)
          .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
          .shadow(color: .black.opacity(0.18), radius: 10, y: 6)

        Text("CAL")
          .font(.headline.weight(.semibold))
          .foregroundStyle(.primary)

        Text("Mid Florida Surgical")
          .font(.subheadline)
          .foregroundStyle(.secondary)
          .lineLimit(1)
      }

      Text("Sign in")
        .font(.system(size: 34, weight: .bold, design: .default))
        .foregroundStyle(.primary)

      Text(todayText)
        .font(.subheadline.weight(.medium))
        .foregroundStyle(.secondary)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
  }
}

private struct CALAuthCard: View {
  @ObservedObject var store: NativeScheduleStore
  @Binding var email: String
  @Binding var code: String
  @Binding var loginRole: NativeSessionRole
  var focusedField: FocusState<NativeAuthView.AuthField?>.Binding
  let requestCode: () -> Void
  let signIn: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      Picker("Sign in as", selection: $loginRole) {
        Text("Surgeon").tag(NativeSessionRole.surgeon)
        Text("Scheduler").tag(NativeSessionRole.scheduler)
      }
      .pickerStyle(.segmented)
      .padding(.bottom, 2)

      Text(
        loginRole == .scheduler
          ? "Scheduler email, tap Send, then enter the 6-digit code."
          : "Surgeon email or iPhone, tap Send, then enter the 6-digit code."
      )
        .font(.caption.weight(.semibold))
        .foregroundStyle(.secondary)
        .lineLimit(2)
        .minimumScaleFactor(0.82)

      TextField("Email or iPhone", text: $email)
        .keyboardType(.emailAddress)
        .textInputAutocapitalization(.never)
        .autocorrectionDisabled()
        .focused(focusedField, equals: .email)
        .textContentType(.emailAddress)
        .submitLabel(.send)
        .onSubmit(requestCode)
        .calAuthFieldStyle()

      HStack(spacing: 10) {
        Button(action: requestCode) {
          Text("Send")
            .font(.subheadline.weight(.bold))
            .foregroundStyle(ClinicalPalette.teal)
            .frame(width: 58, height: 28)
            .background(Color(.secondarySystemBackground), in: Capsule())
        }
        .buttonStyle(.plain)
        .disabled(sendDisabled)

        TextField("6-digit code", text: $code)
          .keyboardType(.numberPad)
          .textContentType(.oneTimeCode)
          .focused(focusedField, equals: .code)
          .submitLabel(.go)
          .onSubmit(signIn)
          .calAuthFieldStyle()
      }

      Button(action: signIn) {
        HStack {
          Text("Sign in")
            .font(.headline.weight(.bold))

          if store.authBusy {
            ProgressView()
              .tint(.white)
          }
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .frame(height: 32)
        .background(LinearGradient.calAuthPrimary, in: Capsule())
      }
      .buttonStyle(.plain)
      .disabled(signInDisabled)

      if let message = store.authMessage, !message.isEmpty {
        Text(message)
          .font(.caption.weight(.medium))
          .foregroundStyle(.secondary)
          .lineLimit(3)
      }
    }
    .padding(9)
  }

  private var normalizedEmail: String {
    email.trimmingCharacters(in: .whitespacesAndNewlines)
  }

  private var normalizedCode: String {
    code.trimmingCharacters(in: .whitespacesAndNewlines)
  }

  private var sendDisabled: Bool {
    store.authBusy || normalizedEmail.isEmpty
  }

  private var signInDisabled: Bool {
    store.authBusy || normalizedEmail.isEmpty || normalizedCode.isEmpty
  }
}

private struct CALAuthBackground: View {
  var body: some View {
    ZStack {
      LinearGradient(
        colors: [
          Color(.systemBackground),
          ClinicalPalette.pageTop,
          Color(.secondarySystemBackground).opacity(0.55)
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
      )

      LinearGradient(
        colors: [
          ClinicalPalette.tealSoft.opacity(0.28),
          .clear,
          ClinicalPalette.teal.opacity(0.06)
        ],
        startPoint: .topTrailing,
        endPoint: .bottomLeading
      )
      .blur(radius: 24)
    }
    .ignoresSafeArea()
  }
}

private extension View {
  func calAuthFieldStyle() -> some View {
    font(.subheadline.weight(.semibold))
      .padding(.horizontal, 10)
      .frame(height: 28)
      .background(Color(.systemBackground), in: Capsule())
      .overlay {
        Capsule()
          .stroke(ClinicalPalette.stroke.opacity(0.85), lineWidth: 1)
      }
  }

  func calAuthGlassSurface(cornerRadius: CGFloat) -> some View {
    background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
      .overlay {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
          .stroke(ClinicalPalette.stroke.opacity(0.85), lineWidth: 1.2)
      }
  }

  func calAuthSoftShadow(prominent: Bool = false) -> some View {
    shadow(color: Color.black.opacity(prominent ? 0.12 : 0.07), radius: prominent ? 18 : 10, y: prominent ? 8 : 4)
  }
}

private extension LinearGradient {
  static let calAuthPrimary = LinearGradient(
    colors: [
      ClinicalPalette.scrubInk,
      ClinicalPalette.teal,
      ClinicalPalette.authAccent
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )
}
