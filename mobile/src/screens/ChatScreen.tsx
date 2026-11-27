import { type ComponentRef, useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { type ChatMode, type ChatReply, createChatSession, sendMessage } from "../api";
import { Button } from "../components";
import { toMessage } from "../errors";
import { colors, shared } from "../theme";

type Turn = { role: "user"; content: string } | { role: "assistant"; reply: ChatReply };

export function ChatScreen() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<ChatMode>("rag");
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<ComponentRef<typeof ScrollView>>(null);
  // Bumped on every session reset so responses from an older session are dropped
  const generationRef = useRef(0);

  const send = async () => {
    const content = input.trim();
    if (!content) return;
    setBusy(true);
    setError(null);
    setTurns((previous) => [...previous, { role: "user", content }]);
    setInput("");
    const generation = generationRef.current;
    const isStale = () => generation !== generationRef.current;
    try {
      const id = sessionId ?? (await createChatSession()).id;
      if (isStale()) return;
      setSessionId(id);
      const reply = await sendMessage(id, content, mode);
      if (isStale()) return;
      setTurns((previous) => [...previous, { role: "assistant", reply }]);
    } catch (err) {
      if (!isStale()) setError(toMessage(err));
    } finally {
      if (!isStale()) setBusy(false);
    }
  };

  const newSession = () => {
    generationRef.current += 1;
    setBusy(false);
    setSessionId(null);
    setTurns([]);
    setError(null);
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={Platform.OS === "ios" ? 90 : 0}
    >
      <View style={styles.toolbar}>
        <Button
          title="RAG answer"
          variant={mode === "rag" ? "primary" : "secondary"}
          disabled={busy}
          onPress={() => setMode("rag")}
        />
        <Button
          title="Agent (may open ticket)"
          variant={mode === "agent" ? "primary" : "secondary"}
          disabled={busy}
          onPress={() => setMode("agent")}
        />
        <Button title="New session" variant="secondary" disabled={busy} onPress={newSession} />
      </View>
      <ScrollView
        ref={scrollRef}
        style={styles.messages}
        contentContainerStyle={styles.messagesContent}
        onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
      >
        {turns.length === 0 && (
          <Text style={shared.muted}>Ask a question about your uploaded knowledge base.</Text>
        )}
        {turns.map((turn, index) =>
          turn.role === "user" ? (
            <View key={index} style={[styles.bubble, styles.userBubble]}>
              <Text style={styles.author}>You</Text>
              <Text style={styles.body}>{turn.content}</Text>
            </View>
          ) : (
            <AssistantMessage key={index} reply={turn.reply} />
          ),
        )}
        {error && <Text style={shared.error}>{error}</Text>}
      </ScrollView>
      <View style={styles.composer}>
        <TextInput
          style={[shared.input, styles.composerInput]}
          value={input}
          onChangeText={setInput}
          placeholder="Question"
          accessibilityLabel="Question"
          multiline
        />
        <Button title={busy ? "Thinking..." : "Send"} onPress={() => void send()} disabled={busy} />
      </View>
    </KeyboardAvoidingView>
  );
}

function AssistantMessage({ reply }: { reply: ChatReply }) {
  return (
    <View style={styles.bubble}>
      <Text style={styles.author}>
        Assistant{reply.refused ? " (refused: no grounded answer)" : ""}
      </Text>
      {reply.status === "awaiting_human" && (
        <View style={styles.banner}>
          <Text style={styles.bannerTitle}>Awaiting human review</Text>
          <Text style={styles.body}>
            Ticket {reply.ticket_id} was opened. Resolve it on the Tickets tab.
          </Text>
        </View>
      )}
      <Text style={styles.body}>{reply.answer}</Text>
      {reply.citations.length > 0 && (
        <View style={styles.citations}>
          <Text style={styles.author}>Citations</Text>
          {reply.citations.map((citation, index) => (
            <Text key={citation.chunk_id} style={styles.body}>
              {index + 1}. {citation.source}: <Text style={styles.quote}>{citation.quote}</Text>
            </Text>
          ))}
        </View>
      )}
      <Text style={shared.muted}>
        {reply.metrics.latency_ms} ms, {reply.metrics.prompt_tokens} prompt /{" "}
        {reply.metrics.completion_tokens} completion tokens
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  toolbar: { flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 12 },
  messages: { flex: 1 },
  messagesContent: { padding: 12, gap: 12 },
  bubble: {
    backgroundColor: colors.surface,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    gap: 6,
  },
  userBubble: { alignSelf: "flex-end", maxWidth: "90%" },
  author: { fontWeight: "700", color: colors.text },
  body: { color: colors.text, fontSize: 15 },
  quote: { fontStyle: "italic", color: colors.muted },
  citations: { gap: 4, marginTop: 4 },
  banner: {
    backgroundColor: colors.warningBackground,
    borderColor: colors.warningBorder,
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    gap: 2,
  },
  bannerTitle: { fontWeight: "700", color: colors.text },
  composer: { flexDirection: "row", gap: 8, padding: 12, alignItems: "flex-end" },
  composerInput: { flex: 1, maxHeight: 120 },
});
