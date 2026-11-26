import { type FormEvent, useState } from "react";
import { type Chunk, listChunks } from "../api";
import { toMessage } from "../errors";
import { loadKnownDocuments } from "../knownDocuments";

export function ChunksPage() {
  const [documents] = useState(loadKnownDocuments);
  const [documentId, setDocumentId] = useState(documents[0]?.id ?? "");
  const [chunks, setChunks] = useState<Chunk[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      setChunks(await listChunks(documentId.trim()));
    } catch (err) {
      setChunks(null);
      setError(toMessage(err));
    }
  };

  return (
    <section>
      <h2>Chunk inspector</h2>
      <form className="row" onSubmit={load}>
        <label>
          Document ID
          <input
            list="known-documents"
            size={40}
            value={documentId}
            onChange={(e) => setDocumentId(e.target.value)}
            required
          />
          <datalist id="known-documents">
            {documents.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </datalist>
        </label>
        <button type="submit">Load chunks</button>
      </form>
      {error && <p className="error">{error}</p>}
      {chunks && (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Section</th>
              <th>Strategy</th>
              <th>Content</th>
              <th>Parent text</th>
            </tr>
          </thead>
          <tbody>
            {chunks.map((c) => (
              <tr key={c.id}>
                <td>{c.chunk_index}</td>
                <td>{c.section ?? ""}</td>
                <td>{c.strategy ?? ""}</td>
                <td>
                  <pre>{c.content}</pre>
                </td>
                <td>
                  <pre>{c.parent_text ?? ""}</pre>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {chunks?.length === 0 && <p className="muted">This document has no chunks.</p>}
    </section>
  );
}
