import { useState } from "react";
import { clearToken, getToken } from "./api";
import { forgetDocuments } from "./knownDocuments";
import { ChatPage } from "./pages/ChatPage";
import { ChunksPage } from "./pages/ChunksPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { LoginPage } from "./pages/LoginPage";
import { TicketsPage } from "./pages/TicketsPage";

const PAGES = {
  documents: { label: "Documents", component: DocumentsPage },
  chunks: { label: "Chunks", component: ChunksPage },
  chat: { label: "Chat", component: ChatPage },
  tickets: { label: "Tickets", component: TicketsPage },
};

type PageKey = keyof typeof PAGES;

export function App() {
  const [authenticated, setAuthenticated] = useState(() => getToken() !== null);
  const [page, setPage] = useState<PageKey>("documents");

  if (!authenticated) {
    return <LoginPage onAuthenticated={() => setAuthenticated(true)} />;
  }

  const logout = () => {
    clearToken();
    forgetDocuments();
    setAuthenticated(false);
  };
  const Page = PAGES[page].component;

  return (
    <>
      <header>
        <h1>Support Copilot Admin</h1>
        <nav>
          {(Object.keys(PAGES) as PageKey[]).map((key) => (
            <button
              key={key}
              className={key === page ? "active" : ""}
              onClick={() => setPage(key)}
            >
              {PAGES[key].label}
            </button>
          ))}
        </nav>
        <button onClick={logout}>Log out</button>
      </header>
      <main>
        <Page />
      </main>
    </>
  );
}
