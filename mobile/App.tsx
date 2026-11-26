import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { clearToken, getToken } from "./src/api";
import { Button } from "./src/components";
import { ChatScreen } from "./src/screens/ChatScreen";
import { LoginScreen } from "./src/screens/LoginScreen";
import { TicketsScreen } from "./src/screens/TicketsScreen";
import { colors } from "./src/theme";

type Tab = "chat" | "tickets";

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [tab, setTab] = useState<Tab>("chat");

  useEffect(() => {
    void getToken().then((token) => setAuthenticated(Boolean(token)));
  }, []);

  const logout = async () => {
    await clearToken();
    setAuthenticated(false);
  };

  if (authenticated === null) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="dark" />
      {authenticated ? (
        <>
          <View style={styles.header}>
            <Text style={styles.title}>Support Copilot</Text>
            <View style={styles.tabs}>
              <Button
                title="Chat"
                variant={tab === "chat" ? "primary" : "secondary"}
                onPress={() => setTab("chat")}
              />
              <Button
                title="Tickets"
                variant={tab === "tickets" ? "primary" : "secondary"}
                onPress={() => setTab("tickets")}
              />
              <Button title="Log out" variant="secondary" onPress={() => void logout()} />
            </View>
          </View>
          {tab === "chat" ? <ChatScreen /> : <TicketsScreen />}
        </>
      ) : (
        <LoginScreen onAuthenticated={() => setAuthenticated(true)} />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    padding: 12,
    gap: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  title: { fontSize: 20, fontWeight: "700", color: colors.text },
  tabs: { flexDirection: "row", gap: 8 },
});
