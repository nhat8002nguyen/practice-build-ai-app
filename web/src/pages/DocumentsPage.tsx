import { type FormEvent, useState } from "react";
import { crawlUrl, type DocumentInfo, uploadDocument } from "../api";
import { toMessage } from "../errors";
import { loadKnownDocuments, rememberDocument } from "../knownDocuments";

const STRATEGIES = ["", "fixed", "heading", "parent_child"];

export function DocumentsPage() {
  const [documents, setDocuments] = useState(loadKnownDocuments);
  const [strategy, setStrategy] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ingest = async (action: () => Promise<DocumentInfo>) => {
    setBusy(true);
    setError(null);
    try {
      setDocuments(rememberDocument(await action()));
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const upload = (event: FormEvent) => {
    event.preventDefault();
    if (file) void ingest(() => uploadDocument(file, strategy));
  };

  const crawl = (event: FormEvent) => {
    event.preventDefault();
    void ingest(() => crawlUrl(url, strategy));
  };

  return (
    <>
      <section>
        <h2>Add knowledge</h2>
        <label>
          Chunk strategy
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            {STRATEGIES.map((s) => (
              <option key={s} value={s}>
                {s || "server default"}
              </option>
            ))}
          </select>
        </label>
        <form className="row" onSubmit={upload}>
          <label>
            Upload PDF or Markdown
            <input
              type="file"
              accept=".pdf,.md,.markdown,.txt"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" disabled={busy || !file}>
            Upload
          </button>
        </form>
        <form className="row" onSubmit={crawl}>
          <label>
            Crawl web page URL
            <input
              type="url"
              value={url}
              placeholder="https://example.com/faq"
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </label>
          <button type="submit" disabled={busy}>
            Crawl
          </button>
        </form>
        {busy && <p className="muted">Indexing...</p>}
        {error && <p className="error">{error}</p>}
      </section>
      <section>
        <h2>Ingested documents (this browser)</h2>
        {documents.length === 0 ? (
          <p className="muted">No documents yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Source</th>
                <th>Status</th>
                <th>Strategy</th>
                <th>Chunks</th>
                <th>Document ID</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d.id}>
                  <td>{d.filename}</td>
                  <td>{d.source_uri ?? d.source_type}</td>
                  <td>{d.status}</td>
                  <td>{d.strategy}</td>
                  <td>{d.chunk_count}</td>
                  <td>
                    <code>{d.id}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
