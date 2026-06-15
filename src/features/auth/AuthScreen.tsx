import { ActivityIndicator, Image, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

type AuthScreenProps = {
  email: string;
  code: string;
  busy: boolean;
  message: string;
  onEmailChange: (v: string) => void;
  onCodeChange: (v: string) => void;
  onRequestOtp: () => void;
  onVerifyOtp: () => void;
};

export function AuthScreen(props: AuthScreenProps) {
  const {
    email,
    code,
    busy,
    message,
    onEmailChange,
    onCodeChange,
    onRequestOtp,
    onVerifyOtp,
  } = props;

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <View style={styles.brandRow}>
          <Image source={require("../../../assets/icon.png")} style={styles.logo} />
          <Text style={styles.brand}>CAL</Text>
          <Text style={styles.practice}>Mid Florida Surgical</Text>
        </View>
        <Text style={styles.title}>Sign in</Text>
        <Text style={styles.today}>{todayLabel()}</Text>
      </View>

      <View style={styles.spacer} />

      <View style={styles.card}>
        <Text style={styles.instruction}>Enter email, tap Send, then enter the 6-digit code.</Text>
        <TextInput
          style={styles.input}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          textContentType="emailAddress"
          value={email}
          onChangeText={onEmailChange}
          placeholder="Email"
          placeholderTextColor="#7d8f92"
          returnKeyType="send"
          onSubmitEditing={onRequestOtp}
        />

        <View style={styles.codeRow}>
          <Pressable
            style={[styles.sendButton, (busy || !email.trim()) && styles.disabled]}
            onPress={onRequestOtp}
            disabled={busy || !email.trim()}
          >
            <Text style={styles.sendText}>Send</Text>
          </Pressable>
          <TextInput
            style={[styles.input, styles.codeInput]}
            keyboardType="number-pad"
            textContentType="oneTimeCode"
            value={code}
            onChangeText={onCodeChange}
            placeholder="6-digit code"
            placeholderTextColor="#7d8f92"
            maxLength={6}
            returnKeyType="go"
            onSubmitEditing={onVerifyOtp}
          />
        </View>

        <Pressable
          style={[styles.button, (busy || !email.trim() || !code.trim()) && styles.disabled]}
          onPress={onVerifyOtp}
          disabled={busy || !email.trim() || !code.trim()}
        >
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Sign in</Text>}
        </Pressable>

        {message ? <Text style={styles.message}>{message}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: "#f0faf8",
    overflow: "hidden",
  },
  header: {
    paddingTop: 8,
    paddingHorizontal: 12,
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
  },
  logo: {
    width: 34,
    height: 34,
    borderRadius: 9,
  },
  brand: {
    color: "#111d22",
    fontSize: 18,
    fontWeight: "800",
  },
  practice: {
    color: "#5c6d70",
    fontSize: 14,
    fontWeight: "600",
    flex: 1,
  },
  title: {
    color: "#111d22",
    fontSize: 34,
    fontWeight: "900",
    marginTop: 8,
  },
  today: {
    color: "#5c6d70",
    fontSize: 14,
    fontWeight: "700",
    marginTop: 3,
  },
  spacer: {
    minHeight: 104,
    flexGrow: 0.18,
  },
  card: {
    backgroundColor: "#fffffbde",
    borderColor: "#d0e5e3",
    borderWidth: 1,
    borderRadius: 18,
    padding: 9,
    marginHorizontal: 12,
    shadowColor: "#143d3d",
    shadowOpacity: 0.14,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 5,
  },
  instruction: {
    color: "#5c6d70",
    fontSize: 12,
    fontWeight: "700",
    marginBottom: 7,
  },
  input: {
    height: 36,
    borderWidth: 1,
    borderColor: "#bad1d1",
    borderRadius: 18,
    paddingHorizontal: 10,
    backgroundColor: "#fffffff2",
    color: "#111d22",
    fontSize: 14,
    fontWeight: "700",
  },
  codeRow: {
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    marginTop: 8,
  },
  sendButton: {
    width: 62,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#eef5f2",
  },
  sendText: {
    color: "#00757f",
    fontSize: 14,
    fontWeight: "900",
  },
  codeInput: {
    flex: 1,
  },
  button: {
    height: 36,
    marginTop: 8,
    backgroundColor: "#0f6f62",
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: {
    color: "#fff",
    fontWeight: "900",
    fontSize: 16,
  },
  message: {
    color: "#5c6d70",
    fontSize: 12,
    fontWeight: "600",
    marginTop: 8,
    lineHeight: 16,
  },
  disabled: {
    opacity: 0.45,
  },
});

function todayLabel(): string {
  return new Date().toLocaleDateString("en-US", {
    weekday: "short",
    month: "2-digit",
    day: "2-digit",
    year: "2-digit",
  });
}
