import { useCallback, useEffect, useState } from "react";
import { FlatList, StyleSheet, Text, TextInput, View } from "react-native";
import { listTickets, resolveTicket, type Ticket } from "../api";
import { Button } from "../components";
import { toMessage } from "../errors";
import { colors, shared } from "../theme";

export function TicketsScreen() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setTickets(await listTickets());
      setError(null);
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const resolve = async (id: string, decision: "approve" | "reject") => {
    setResolvingId(id);
    setError(null);
    try {
      await resolveTicket(id, decision, notes[id] ?? "");
      await refresh();
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setResolvingId(null);
    }
  };

  return (
    <View style={styles.container}>
      {error && <Text style={[shared.error, styles.padded]}>{error}</Text>}
      <FlatList
        data={tickets}
        keyExtractor={(ticket) => ticket.id}
        refreshing={loading}
        onRefresh={() => void refresh()}
        contentContainerStyle={styles.list}
        ListEmptyComponent={<Text style={shared.muted}>No tickets. Pull down to refresh.</Text>}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text style={styles.subject}>{item.subject}</Text>
            {item.description && <Text style={styles.body}>{item.description}</Text>}
            <Text style={shared.muted}>
              Priority: {item.priority} | Status: {item.status} |{" "}
              {new Date(item.created_at).toLocaleString()}
            </Text>
            {item.status === "open" ? (
              <>
                <TextInput
                  style={shared.input}
                  placeholder="Optional note"
                  accessibilityLabel={`Note for ${item.subject}`}
                  value={notes[item.id] ?? ""}
                  onChangeText={(text) => setNotes({ ...notes, [item.id]: text })}
                />
                <View style={styles.actions}>
                  <Button
                    title="Approve"
                    disabled={resolvingId === item.id}
                    onPress={() => void resolve(item.id, "approve")}
                  />
                  <Button
                    title="Reject"
                    variant="danger"
                    disabled={resolvingId === item.id}
                    onPress={() => void resolve(item.id, "reject")}
                  />
                </View>
              </>
            ) : (
              item.resolution_note && (
                <Text style={styles.body}>Resolution: {item.resolution_note}</Text>
              )
            )}
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  padded: { paddingHorizontal: 12 },
  list: { padding: 12, gap: 12 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    gap: 8,
  },
  subject: { fontWeight: "700", fontSize: 16, color: colors.text },
  body: { color: colors.text, fontSize: 15 },
  actions: { flexDirection: "row", gap: 12 },
});
