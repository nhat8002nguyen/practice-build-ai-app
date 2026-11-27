const API_BASE = import.meta.env.VITE_API_URL ?? "/api";
const TOKEN_KEY = "copilot_token";

export interface DocumentInfo {
  id: string;
  filename: string;
  source_type: string;
  source_uri: string | null;
  status: string;
  strategy: string;
  chunk_count: number;
}

export interface Chunk {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  section: string | null;
  strategy: string | null;
  qdrant_point_id: string | null;
  parent_text: string | null;
}

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

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY);
export const setToken = (token: string): void => localStorage.setItem(TOKEN_KEY, token);
export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY);

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
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (typeof init.body === "string") headers.set("Content-Type", "application/json");

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

export const uploadDocument = (file: File, strategy: string) => {
  const form = new FormData();
  form.append("file", file);
  return request<DocumentInfo>(`/documents/upload${strategyQuery(strategy)}`, {
    method: "POST",
    body: form,
  });
};

export const crawlUrl = (url: string, strategy: string) =>
  post<DocumentInfo>(`/documents/crawl${strategyQuery(strategy)}`, { url });

const strategyQuery = (strategy: string) =>
  strategy ? `?strategy=${encodeURIComponent(strategy)}` : "";

export const listChunks = (documentId: string) =>
  request<Chunk[]>(`/admin/chunks?document_id=${encodeURIComponent(documentId)}`);

export const createChatSession = () => post<{ id: string }>("/chat/sessions", {});

export const sendMessage = (sessionId: string, content: string, mode: ChatMode) =>
  post<ChatReply>(`/chat/sessions/${sessionId}/messages`, { content, mode });

export const listTickets = () => request<Ticket[]>("/tickets");

export const resolveTicket = (id: string, decision: "approve" | "reject", note: string) =>
  post<Ticket>(`/tickets/${id}/resolve`, { decision, note: note || null });
