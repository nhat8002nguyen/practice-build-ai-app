import { type FormEvent, useState } from "react";
import { authenticate, setToken } from "../api";
import { toMessage } from "../errors";

export function LoginPage({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const mode = submitter?.value === "register" ? "register" : "login";
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await authenticate(mode, email, password);
      setToken(access_token);
      onAuthenticated();
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="login">
      <h1>Support Copilot Admin</h1>
      <form onSubmit={submit}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Password (min 8 characters)
          <input
            type="password"
            value={password}
            minLength={8}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="row">
          <button type="submit" value="login" disabled={busy}>
            Log in
          </button>
          <button type="submit" value="register" disabled={busy}>
            Register
          </button>
        </div>
      </form>
    </section>
  );
}
