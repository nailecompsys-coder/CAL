import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

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
    <View style={styles.card}>
      <Text style={styles.label}>Surgeon Email</Text>
      <TextInput
        style={styles.input}
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={onEmailChange}
        placeholder="name@domain.com"
      />
      <Pressable style={styles.button} onPress={onRequestOtp} disabled={busy || !email.trim()}>
        <Text style={styles.buttonText}>Request OTP</Text>
      </Pressable>

      <Text style={[styles.label, { marginTop: 16 }]}>OTP Code</Text>
      <TextInput
        style={styles.input}
        keyboardType="number-pad"
        value={code}
        onChangeText={onCodeChange}
        placeholder="6-digit code"
        maxLength={6}
      />
      <Pressable
        style={styles.button}
        onPress={onVerifyOtp}
        disabled={busy || !email.trim() || code.trim().length !== 6}
      >
        <Text style={styles.buttonText}>Verify + Login</Text>
      </Pressable>

      <View style={styles.footer}>
        {busy ? <ActivityIndicator /> : <Text style={styles.message}>{message}</Text>}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 14,
    shadowColor: "#000",
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
    flex: 1,
  },
  label: {
    fontWeight: "600",
    color: "#243b5a",
    marginBottom: 6,
  },
  input: {
    borderWidth: 1,
    borderColor: "#d3dbea",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    backgroundColor: "#fff",
  },
  button: {
    marginTop: 10,
    backgroundColor: "#1f5fbf",
    borderRadius: 8,
    paddingVertical: 11,
    alignItems: "center",
  },
  buttonText: {
    color: "#fff",
    fontWeight: "700",
  },
  footer: {
    minHeight: 26,
    justifyContent: "center",
    marginTop: 10,
  },
  message: {
    color: "#3d4f69",
  },
});
