# Interview answers for the RAG AI Engineer role

These answers are grounded in this repository (SMB Support Knowledge Copilot).
They match the five application questions in `upwork-requirement.txt`.
Every claim below points at something that exists in the code, so it is safe to say aloud.

Ownership gate F (Nate): run a mock interview from this file without reading the code.
Pass when you can answer each question and its follow-ups in your own words.

## Q1. A production RAG application: which LLM, vector database, and framework?

**Short answer**

I built a support knowledge copilot for small businesses.
It ingests markdown, PDFs, and crawled web pages, and answers with citations or refuses.

**Stack**

- LLMs: OpenAI `gpt-4o-mini` by default, Anthropic Claude (`claude-haiku-4-5`) through a provider switch (`LLM_PROVIDER`).
  Both sit behind one small `LLM` interface, so the retrieval, citation, and refusal logic is identical.
- Vector database: Qdrant (cosine distance), with embeddings from OpenAI `text-embedding-3-small`.
- Retrieval: hybrid, dense from Qdrant plus BM25 over the same user's chunks, merged with a 0.7 dense weight.
- Backend: FastAPI, async SQLAlchemy on Postgres, Redis for rate limiting.
- Orchestration: LangGraph for the agent.
  The RAG path is plain Python on purpose, so each step (retrieve, gate, generate, verify) can be tested alone.
- Clients: Vite and React admin UI, Expo mobile app, n8n workflow.
- Deploy: Docker Compose locally. A VPS setup (Nginx, Let's Encrypt TLS) is configured and documented but not yet deployed.

**Be ready for**

- *Why not LangChain or LlamaIndex?*
  The pipeline is small and I wanted full control over citation verification and refusals.
  I know the trade-off: frameworks save time on loaders and connectors, but hide the steps I needed to test.
  I would use them where connectors matter, for example many document sources.
- *Is it deployed?*
  Not yet.
  The VPS deployment is designed and configured (`deploy/docker-compose.prod.yml`, Nginx with TLS, step-by-step README), but it has not been deployed or verified on a live server.
  Locally the full stack runs with Docker Compose.
  Do not claim a live demo until Nate deploys it, then fill in the live URL: `<live URL>`.
- *Why Postgres and Qdrant both?*
  Postgres is the source of truth, Qdrant is a search index.
  Retrieval hydrates every hit from Postgres and drops hits whose document is not `ready`, so stale or orphaned vectors never reach the model.

## Q2. AI agents with LangGraph

**Short answer**

Yes.
The chat endpoint has an `agent` mode built on a LangGraph `StateGraph` with human-in-the-loop approval.

**The graph** (`backend/app/agents/graph.py`)

- Nodes: `assistant`, `tools`, `hitl`, `finalize`.
- `assistant` asks the model for one JSON step: a tool call or a final answer.
- `tools` runs `search_knowledge` (the same grounded RAG pipeline), `lookup_order` (a stub standing in for an e-commerce API), or `create_ticket`.
- If a ticket was created, the graph goes to `hitl`, which calls `interrupt()`.
  State is checkpointed and the API returns "awaiting human" with a ticket ID.
- A person approves or rejects through `POST /tickets/{id}/resolve`, which resumes the graph with `Command(resume=...)`.
  `finalize` then replies with the human decision.

**Example**

A customer asks for a refund for an order that is not found.
The agent looks up the order, gets `found=false`, creates a ticket, and the customer sees "awaiting human review".
After an agent approves in the admin UI or the mobile app, the conversation shows the decision.

**Guardrails worth mentioning**

- Maximum 6 assistant steps, then a safe fallback message.
- Malformed model output becomes a fallback answer, not a crash.
- Tool errors go back to the model as observations so it can correct itself.
- `create_ticket` is idempotent per run, keyed by the thread ID, so a retry cannot open duplicate tickets.
- Tickets and tool searches are scoped to the logged-in user.

**Be ready for**

- *What is the weak spot?*
  The checkpointer is in-memory `MemorySaver`.
  A paused run is lost on API restart, resolve returns 409, and the ticket stays open.
  The fix is the LangGraph Postgres checkpointer, and I documented it in `aws-portability.md` and the code comment.
- *Multi-agent?*
  This is a single agent with tools.
  I would split into multiple agents only when one prompt can no longer hold the tool set or policy.

## Q3. n8n automation and third-party integrations

**Short answer**

I built a draft-reply workflow: `n8n/workflows/draft-reply.json`.

**How it works**

1. A webhook node receives a ticket (`subject`, `body`, optional `customer_email`).
2. An HTTP Request node calls `POST /drafts/reply` on the API with a shared secret header.
3. A second HTTP Request node posts the grounded draft, citations, and the `refused` flag to a Slack incoming webhook for human review.

**Design choices**

- The API authenticates n8n with a shared `X-N8N-Secret`, compared in constant time.
  An empty configured secret rejects everything.
- The draft endpoint searches only the documents of one configured owner (`DRAFT_USER_EMAIL`).
- It reuses the exact RAG pipeline, so drafts cite sources and refuse when evidence is missing.
- Nothing is sent to the customer automatically, a human reads the Slack message first.
- The endpoint is rate limited with a Redis token bucket, so a looping workflow cannot burn the LLM budget.
- Secrets reach n8n through environment variables, never in the exported workflow JSON.

**Be ready for**

- *Other integrations?*
  Slack through incoming webhooks, OpenAI and Anthropic APIs, and a public web crawler with SSRF checks (only public hosts are fetched).
  The order lookup is a stub, I would be explicit that it is not a real CRM or e-commerce integration yet.
- *WordPress, Drupal, CRM?*
  Not built here.
  The pattern would be the same: n8n webhook in, API call, human approval out.

## Q4. Evaluating accuracy, preventing hallucinations, optimizing tokens

**Evaluation** (`backend/evals/`)

- A golden set of 31 questions over fixture documents, including questions that must be refused.
- Metrics: hit_rate@k and recall@k for retrieval, correct and false refusal rates, latency p50 and p95, average context tokens, estimated cost.
- A chunking experiment compares six variants of `fixed`, `heading`, and `parent_child` and writes the table into `chunking-decision-record.md`.
- Run it with `PYTHONPATH=. python -m evals.run_eval --llm mock` for a key-free run.

Honest caveats to say out loud:

- Current numbers use a hash embedder and a mock LLM, so they validate the harness and compare chunking variants lexically.
  They are not a claim about production answer quality.
- The default variant scores hit_rate@3 0.92 and recall@3 0.92 on that setup, at about 92 context tokens per query.
- The next step is real embeddings (`--embedder openai`), real SMB documents, and a larger golden set.

**Preventing hallucinations** (`backend/app/rag/generate.py`)

1. Retrieval gate: if the best merged score is under `RETRIEVAL_MIN_SCORE` (0.3, tuned for dense weight 0.7), refuse without calling the model.
2. Prompt: answer only from the excerpts, return JSON, or return `insufficient_evidence`.
3. Citation verification: each citation must reference a retrieved chunk and quote it verbatim.
   Quotes must have at least 20 characters and 4 words, so a one-word match does not count.
4. Number check: every figure in the answer (days, prices, limits) must appear in a cited chunk.
5. Anything that fails becomes a refusal: "I don't know based on the knowledge base."

I prefer a false refusal over a confident wrong policy answer, because wrong policy has a real cost for a support team.

**Token and cost control**

- Parent-child chunking: small children for precise retrieval, parent text for context, so the model gets a coherent section instead of a whole document.
- Top 5 chunks only, and history is limited to the last `CHAT_HISTORY_TURNS` (6) exchanges.
- Refusals from the retrieval gate cost zero model tokens.
- Each query logs retrieved IDs, scores, latency, token usage, and an estimated USD cost, and the API returns the same metrics to the client.
- Model timeouts and a per-user rate limit cap worst-case spend.
- A cheap default model (`gpt-4o-mini`) with a one-line switch to Claude.

**Be ready for**

- *How do you measure faithfulness today?*
  By construction (verified quotes and numbers) rather than an LLM judge.
  An LLM-as-judge pass on the golden set is a sensible next addition, and I would say it is not built.
- *Why is the false refusal rate 0.24 in the mock run?*
  The mock LLM and hash embedder cannot bridge paraphrases such as "cards" versus "Visa, Mastercard".
  That is the reason to re-run with real embeddings before changing defaults.

## Q5. Repositories, live apps, portfolio

- Repository: `<GitHub URL>`.
- Live demo: `<live URL>` (placeholder until the VPS deploy is done), then the mobile client can point at the same API.
- Read first: `README.md`, `docs/portfolio/architecture.md`, `docs/portfolio/chunking-decision-record.md`.
- Tests: backend unit and integration tests run in GitHub Actions with a mocked LLM and in-memory Qdrant, so CI needs no keys.

## Role requirements versus this repo

| Requirement | Status in this repo |
| --- | --- |
| OpenAI, Claude | Both, behind one `LLM` interface |
| Gemini | Not integrated. A new provider is one class implementing `complete()` |
| LangGraph | Used for the agent |
| LangChain, LlamaIndex | Not used by design |
| Vector DB | Qdrant. Pinecone, FAISS, Weaviate, Chroma not used |
| FastAPI, async | Yes |
| n8n, webhooks | Draft-reply workflow with Slack |
| PostgreSQL, Redis | Both used. Redis holds rate limit buckets |
| MongoDB | Not used |
| Docker, GitHub Actions | Compose for local, VPS config written but not yet deployed, Actions runs tests |
| AWS | Documentation only, see `aws-portability.md` |
| Human-in-the-loop, memory, tool calling | Yes, in the agent and tickets |
| Structured outputs | JSON replies parsed and validated, citations verified |

## Hard follow-ups

- *What breaks first at 100x load?*
  Per-query BM25 over a user's chunks, the in-memory agent checkpointer, and in-request ingestion.
  The rate limiter and API tasks already scale horizontally.
- *How do you keep one customer's data from leaking into another's answers?*
  Every Qdrant search filters on the owner and every Postgres query joins on `user_id`.
- *What if Redis is down?*
  The limiter fails open and logs a warning, so support stays up.
  I chose availability over strict limiting, and the LLM timeout still bounds each request.
- *Why Nginx and Compose instead of Kubernetes or ECS?*
  One VPS fits the scale and cost.
  The containers and env-based config port to ECS, as mapped in `aws-portability.md`.
