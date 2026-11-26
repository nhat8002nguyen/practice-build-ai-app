import { type FormEvent, useState } from "react";
import { type ChatMode, type ChatReply, createChatSession, sendMessage } from "../api";
import { toMessage } from "../errors";

type Turn = { role: "user"; content: string } | { role: "assistant"; reply: ChatReply };

export function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<ChatMode>("rag");
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const content = input.trim();
    if (!content) return;
    setBusy(true);
    setError(null);
    setTurns((previous) => [...previous, { role: "user", content }]);
    setInput("");
    try {
      const id = sessionId ?? (await createChatSession()).id;
      setSessionId(id);
      const reply = await sendMessage(id, content, mode);
      setTurns((previous) => [...previous, { role: "assistant", reply }]);
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const newSession = () => {
    setSessionId(null);
    setTurns([]);
    setError(null);
  };

  return (
    <section>
      <h2>Chat</h2>
      <div className="row">
        <label>
          Mode
          <select value={mode} onChange={(e) => setMode(e.target.value as ChatMode)}>
            <option value="rag">RAG answer</option>
            <option value="agent">Agent (tools, may open a ticket)</option>
          </select>
        </label>
        <button onClick={newSession}>New session</button>
      </div>
      {turns.map((turn, index) =>
        turn.role === "user" ? (
          <div key={index} className="message user">
            <strong>You:</strong> {turn.content}
          </div>
        ) : (
          <AssistantMessage key={index} reply={turn.reply} />
        ),
      )}
      {error && <p className="error">{error}</p>}
      <form className="row" onSubmit={send}>
        <label>
          Question
          <input size={60} value={input} onChange={(e) => setInput(e.target.value)} />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Thinking..." : "Send"}
        </button>
      </form>
    </section>
  );
}

function AssistantMessage({ reply }: { reply: ChatReply }) {
  return (
    <div className="message">
      <strong>Assistant{reply.refused ? " (refused: no grounded answer)" : ""}:</strong>
      <pre>{reply.answer}</pre>
      {reply.status === "awaiting_human" && (
        <p>
          Awaiting human review. Ticket <code>{reply.ticket_id}</code> - resolve it on the Tickets
          page.
        </p>
      )}
      {reply.citations.length > 0 && (
        <>
          <strong>Citations</strong>
          <ol>
            {reply.citations.map((c) => (
              <li key={c.chunk_id}>
                {c.source}: <em>{c.quote}</em>
              </li>
            ))}
          </ol>
        </>
      )}
      <p className="muted">
        {reply.metrics.latency_ms} ms, {reply.metrics.prompt_tokens} prompt /{" "}
        {reply.metrics.completion_tokens} completion tokens
      </p>
    </div>
  );
}
