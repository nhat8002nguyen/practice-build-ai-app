import * as SecureStore from "expo-secure-store";

const API_BASE = (process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const TOKEN_KEY = "copilot_token";

export interface Citation {
  chunk_id: string;
  source: string;
  quote: string;
}

export interface ChatReply {
  answer: string;
  refused: boolean;
  citations: Citation[];
  metrics: { latency_ms: number; prompt_tokens: number; completion_tokens: number };
  status: "answered" | "awaiting_human";
  ticket_id: string | null;
}

export interface Ticket {
  id: string;
  session_id: string | null;
  subject: string;
  description: string | null;
  status: string;
  priority: string;
  resolution_note: string | null;
  created_at: string;
}

export type ChatMode = "rag" | "agent";

export const getToken = () => SecureStore.getItemAsync(TOKEN_KEY);
export const setToken = (token: string) => SecureStore.setItemAsync(TOKEN_KEY, token);
export const clearToken = () => SecureStore.deleteItemAsync(TOKEN_KEY);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg ?? JSON.stringify(item)).join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = await getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (typeof init.body === "string") headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      errorMessage(body?.detail, `Request failed (${response.status})`),
    );
  }
  return response.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const authenticate = (mode: "login" | "register", email: string, password: string) =>
  post<{ access_token: string }>(`/auth/${mode}`, { email, password });

export const createChatSession = () => post<{ id: string }>("/chat/sessions", {});

export const sendMessage = (sessionId: string, content: string, mode: ChatMode) =>
  post<ChatReply>(`/chat/sessions/${sessionId}/messages`, { content, mode });

export const listTickets = () => request<Ticket[]>("/tickets");

export const resolveTicket = (id: string, decision: "approve" | "reject", note: string) =>
  post<Ticket>(`/tickets/${id}/resolve`, { decision, note: note || null });
