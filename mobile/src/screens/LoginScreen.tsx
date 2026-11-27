import { useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";
import { authenticate, setToken } from "../api";
import { Button } from "../components";
import { toMessage } from "../errors";
import { colors, shared } from "../theme";

export function LoginScreen({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (mode: "login" | "register") => {
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await authenticate(mode, email.trim(), password);
      await setToken(access_token);
      onAuthenticated();
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Support Copilot</Text>
      <Text style={shared.label}>Email</Text>
      <TextInput
        style={shared.input}
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        accessibilityLabel="Email"
      />
      <Text style={[shared.label, styles.gap]}>Password (min 8 characters)</Text>
      <TextInput
        style={shared.input}
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        accessibilityLabel="Password"
      />
      {error && <Text style={shared.error}>{error}</Text>}
      <View style={styles.actions}>
        <Button title="Log in" onPress={() => void submit("login")} disabled={busy} />
        <Button
          title="Register"
          variant="secondary"
          onPress={() => void submit("register")}
          disabled={busy}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: "center", padding: 24, backgroundColor: colors.background },
  title: { fontSize: 28, fontWeight: "700", color: colors.text, marginBottom: 24 },
  gap: { marginTop: 12 },
  actions: { flexDirection: "row", gap: 12, marginTop: 16 },
});
