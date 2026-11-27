import { useCallback, useEffect, useState } from "react";
import { listTickets, resolveTicket, type Ticket } from "../api";
import { toMessage } from "../errors";

export function TicketsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setTickets(await listTickets());
      setError(null);
    } catch (err) {
      setError(toMessage(err));
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
    <section>
      <h2>Tickets</h2>
      <button onClick={() => void refresh()}>Refresh</button>
      {error && <p className="error">{error}</p>}
      {tickets.length === 0 ? (
        <p className="muted">No tickets.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Subject</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Created</th>
              <th>Resolution</th>
            </tr>
          </thead>
          <tbody>
            {tickets.map((t) => (
              <tr key={t.id}>
                <td>
                  {t.subject}
                  {t.description && <div className="muted">{t.description}</div>}
                </td>
                <td>{t.priority}</td>
                <td>{t.status}</td>
                <td>{new Date(t.created_at).toLocaleString()}</td>
                <td>
                  {t.status === "open" ? (
                    <div className="row">
                      <input
                        aria-label={`Note for ${t.subject}`}
                        placeholder="Optional note"
                        value={notes[t.id] ?? ""}
                        onChange={(e) => setNotes({ ...notes, [t.id]: e.target.value })}
                      />
                      <button disabled={resolvingId === t.id} onClick={() => void resolve(t.id, "approve")}>
                        Approve
                      </button>
                      <button disabled={resolvingId === t.id} onClick={() => void resolve(t.id, "reject")}>
                        Reject
                      </button>
                    </div>
                  ) : (
                    (t.resolution_note ?? "")
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
