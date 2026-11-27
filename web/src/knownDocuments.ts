import type { DocumentInfo } from "./api";

// The API has no list-documents endpoint, so ingested documents are remembered locally.
const KEY = "copilot_documents";

export function loadKnownDocuments(): DocumentInfo[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as DocumentInfo[];
  } catch {
    return [];
  }
}

export function rememberDocument(document: DocumentInfo): DocumentInfo[] {
  const documents = [document, ...loadKnownDocuments().filter((d) => d.id !== document.id)];
  localStorage.setItem(KEY, JSON.stringify(documents));
  return documents;
}

export function forgetDocuments(): void {
  localStorage.removeItem(KEY);
}
