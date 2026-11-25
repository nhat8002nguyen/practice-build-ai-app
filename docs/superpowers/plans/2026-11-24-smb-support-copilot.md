# SMB Support Knowledge Copilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a production-shaped SMB Support Knowledge Copilot (FastAPI RAG + LangGraph agent + Qdrant + Postgres/Redis + Vite admin + Expo RN + n8n + VPS Docker) that Nate can demo live and defend in interviews.

**Architecture:** Thin clients (Vite admin + Expo) call one FastAPI service that owns ingest, hybrid RAG with citations, LangGraph tools/HITL, and draft-reply for n8n. Qdrant, Postgres, and Redis run beside the API via Docker Compose on Nate's VPS (Nginx terminates TLS).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async + asyncpg, Redis, Qdrant, LangGraph/LangChain, OpenAI + Anthropic, Vite + React 18, Expo (Node 22), n8n, Docker Compose, Nginx, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-24-smb-support-copilot-learning-design.md`

## Execution model (agent-speed + ownership)

This plan assumes **AI agents write most code in one dense day** (or two short sessions), not an 8-12 week human typing schedule.

The design doc's "weeks" remain useful as **learning phases**, not coding ETA.

| Layer | Owner | Cadence |
|-------|--------|---------|
| Scaffold, wiring, tests, deploy configs | Agent | Hours |
| Chunking experiment numbers + decision record | Agent runs harness; Nate interprets | Same day |
| Explain aloud / mock interview | Nate | Before claiming mastery |
| Real SMB partner onboarding | Nate | After MVP runs locally/on VPS |

**Ownership gate (required after Tasks 3, 5, 6, 8, 10):** Nate answers the gate questions in chat or a short voice note before the next major feature is treated as "learned." Agents may continue scaffolding if Nate opts in, but gates stay on the definition of done for skills.

## Global Constraints

- Deploy target: existing VPS via Docker Compose + Nginx (not paid AWS for MVP).
- Vector DB: self-hosted Qdrant in Compose (not Pinecone for MVP).
- LangGraph primary; do not add LlamaIndex unless a task explicitly needs it (MVP: no LlamaIndex).
- LLM: OpenAI primary; Anthropic Claude on one configurable path.
- Single-business tenant v1; no multi-tenant SaaS.
- Mobile is a thin client; no on-device RAG.
- No em dash in docs/commit messages (project style).
- Secrets only in `.env` (gitignored); ship `.env.example`.
- Prefer small focused files; one clear responsibility per module.
- TDD for pure logic (chunkers, retrieval scoring helpers, auth token helpers, eval metrics). API wiring may use integration tests.
- Node 22 for web/mobile toolchains; Python 3.12 for API.

---

## File structure (create these units)

```text
backend/
  pyproject.toml                 # deps + pytest
  Dockerfile
  app/
    __init__.py
    main.py                      # FastAPI app factory + routers
    core/
      config.py                  # pydantic-settings from env
      db.py                      # async engine/session
      redis.py
      security.py                # JWT/password helpers
      logging.py
    models/
      entities.py                # SQLAlchemy: User, Document, ChunkMeta, Session, Message, Ticket, EvalRun
    schemas/
      api.py                     # Pydantic request/response models
    api/
      deps.py
      health.py
      auth.py
      documents.py
      chat.py
      tickets.py
      drafts.py                  # n8n draft-reply
      admin_chunks.py            # inspect chunks
    rag/
      normalize.py
      chunking.py                # fixed, heading, parent_child
      embeddings.py
      store.py                   # Qdrant upsert/search
      retrieve.py                # hybrid retrieve
      generate.py                # cited answer + refusal
      pipeline.py                # ingest orchestration
    agents/
      tools.py                   # search_knowledge, lookup_order, create_ticket
      graph.py                   # LangGraph definition + HITL
      memory.py                  # load/save conversation turns
    services/
      crawl.py                   # small FAQ/site crawl
      metrics.py                 # latency/cost logging
      llm.py                     # OpenAI + Claude providers
  tests/
    unit/
      test_chunking.py
      test_security.py
      test_metrics.py
      test_retrieve_ranking.py
    integration/
      test_health.py
      test_ingest_retrieve.py
      test_chat_citations.py
      test_agent_escalate.py
  evals/
    golden_set.json
    run_eval.py
    chunking_experiment.py
web/
  package.json
  vite.config.ts
  src/
    main.tsx
    api/client.ts
    pages/Login.tsx
    pages/Documents.tsx
    pages/Chunks.tsx
    pages/Chat.tsx
    pages/Tickets.tsx
mobile/
  package.json
  app.json
  App.tsx
  src/api/client.ts
  src/screens/LoginScreen.tsx
  src/screens/ChatScreen.tsx
  src/screens/TicketScreen.tsx
n8n/
  workflows/draft-reply.json     # exportable workflow
deploy/
  nginx.conf
  docker-compose.yml             # api, worker(optional), postgres, redis, qdrant, n8n, web
  docker-compose.prod.yml        # overrides for VPS
.github/workflows/ci.yml
.env.example
README.md
docs/portfolio/
  architecture.md
  chunking-decision-record.md
  jd-qa.md
  aws-portability.md
```

---

### Task 1: Monorepo skeleton + Compose + health API

**Files:**
- Create: `backend/pyproject.toml`, `backend/Dockerfile`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/core/logging.py`, `backend/app/api/health.py`, `backend/tests/integration/test_health.py`
- Create: `deploy/docker-compose.yml`, `deploy/nginx.conf`, `.env.example`, `.gitignore` (extend), `README.md` (stub)
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: none
- Produces: `GET /health` → `{"status":"ok"}`; Compose services `api`, `postgres`, `redis`, `qdrant` startable locally

- [ ] **Step 1: Write failing health test**

```python
# backend/tests/integration/test_health.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/integration/test_health.py -v`  
Expected: FAIL (app or module missing)

- [ ] **Step 3: Implement minimal FastAPI app + config**

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "smb-support-copilot"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/copilot"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    jwt_secret: str = "dev-only-change-me"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:8081"

    class Config:
        env_file = ".env"

settings = Settings()
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.health import router as health_router
from app.core.config import settings

def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    return app

app = create_app()
```

```python
# backend/app/api/health.py
from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Add `pyproject.toml` with fastapi, uvicorn, pydantic-settings, pytest, httpx; make tests pass**

Run: `cd backend && pip install -e ".[dev]" && pytest tests/integration/test_health.py -v`  
Expected: PASS

- [ ] **Step 5: Add Compose + `.env.example` + CI lint/test job**

`deploy/docker-compose.yml` must define services: `api` (build backend), `postgres:16`, `redis:7`, `qdrant`, volumes, and published ports `8000`, `5432`, `6379`, `6333`.  
CI: on push, install backend deps and run `pytest`.

- [ ] **Step 6: Commit**

```bash
git add backend deploy .env.example .github README.md .gitignore
git commit -m "feat: scaffold FastAPI health API and local Compose stack"
```

---

### Task 2: Auth + Postgres models + Redis ping

**Files:**
- Create: `backend/app/core/db.py`, `backend/app/core/redis.py`, `backend/app/core/security.py`, `backend/app/models/entities.py`, `backend/app/schemas/api.py`, `backend/app/api/auth.py`, `backend/app/api/deps.py`
- Create: `backend/tests/unit/test_security.py`
- Modify: `backend/app/main.py` (include auth router; lifespan create tables)

**Interfaces:**
- Consumes: `settings.database_url`, `settings.jwt_secret`, `settings.redis_url`
- Produces:
  - `POST /auth/register` `{email, password}` → `{access_token, token_type}`
  - `POST /auth/login` → same
  - `get_current_user` dependency
  - Entities: `User`, `Document`, `ChunkRecord`, `ChatSession`, `Message`, `Ticket`

- [ ] **Step 1: Write failing security unit tests**

```python
# backend/tests/unit/test_security.py
from app.core.security import hash_password, verify_password, create_access_token, decode_access_token

def test_password_roundtrip():
    h = hash_password("secret123")
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)

def test_jwt_roundtrip():
    token = create_access_token(subject="user-1")
    assert decode_access_token(token)["sub"] == "user-1"
```

- [ ] **Step 2: Run tests - expect FAIL**

Run: `pytest backend/tests/unit/test_security.py -v`

- [ ] **Step 3: Implement security helpers (bcrypt/passlib or pwdlib + PyJWT)**

```python
# backend/app/core/security.py
from datetime import datetime, timedelta, timezone
from typing import Any
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def create_access_token(subject: str, expires_minutes: int = 60 * 24) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire},
        settings.jwt_secret,
        algorithm="HS256",
    )

def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
```

- [ ] **Step 4: Implement SQLAlchemy models + register/login routes + Redis client ping on `/health` optional detail**

Keep register/login synchronous-password hashing off the event loop via `asyncio.to_thread` if needed.

- [ ] **Step 5: Integration smoke - register then login**

```python
def test_register_and_login():
    email = "ops@example.com"
    password = "secret123"
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200
    r2 = client.post("/auth/login", json={"email": email, "password": password})
    assert r2.status_code == 200
    assert "access_token" in r2.json()
```

Use a test DB URL or SQLite only if asyncpg setup is heavy; prefer Postgres from Compose for integration. Document `DATABASE_URL` for tests in README.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: add JWT auth and core Postgres models"
```

---

### Task 3: Ingest + three chunkers + Qdrant upsert + chunk inspect API

**Files:**
- Create: `backend/app/rag/normalize.py`, `chunking.py`, `embeddings.py`, `store.py`, `pipeline.py`, `backend/app/services/crawl.py`
- Create: `backend/app/api/documents.py`, `backend/app/api/admin_chunks.py`
- Create: `backend/tests/unit/test_chunking.py`, `backend/tests/integration/test_ingest_retrieve.py`
- Create: `backend/evals/fixtures/sample_policy.md` (synthetic support policy for tests)

**Interfaces:**
- Consumes: auth user; OpenAI embeddings (allow fake embedder in tests)
- Produces:
  - `chunk_fixed(text, size_tokens=512, overlap_ratio=0.12) -> list[Chunk]`
  - `chunk_by_heading(text, ...) -> list[Chunk]`
  - `chunk_parent_child(text, ...) -> list[Chunk]` where each child has `parent_text`
  - `POST /documents/upload` (multipart PDF/MD)
  - `POST /documents/crawl` `{url}`
  - `GET /admin/chunks?document_id=`
  - Qdrant collection `knowledge_chunks` with payload metadata

**Chunk dataclass:**

```python
@dataclass
class Chunk:
    text: str
    index: int
    section: str | None
    parent_text: str | None
    strategy: str  # fixed | heading | parent_child
```

- [ ] **Step 1: Write failing chunking tests** (fixed splits, heading respects `#`, parent_child sets parent_text, FAQ-like blocks)

```python
def test_heading_chunk_keeps_refund_section_together():
    text = "# Refunds\nFull refund in 14 days.\n# Shipping\nShips in 2 days.\n"
    chunks = chunk_by_heading(text, max_tokens=200, overlap_ratio=0.1)
    assert any("14 days" in c.text and "Ships" not in c.text for c in chunks)
```

- [ ] **Step 2: Implement chunkers + normalize; tests PASS**

- [ ] **Step 3: Implement embedder interface**

```python
class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

Provide `OpenAIEmbedder` and `HashEmbedder` (deterministic, for tests only).

- [ ] **Step 4: Qdrant store upsert/search + ingest pipeline writing Document + ChunkRecord rows**

Default ingest strategy env: `CHUNK_STRATEGY=parent_child` (others selectable for experiments).

- [ ] **Step 5: API upload + list chunks; integration test with HashEmbedder**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: document ingest with fixed, heading, and parent-child chunking"
```

**Ownership gate A (Nate):** Explain fixed vs heading vs parent-child and when FAQ atomic chunks win. Do not skip.

---

### Task 4: Hybrid retrieve + cited generate + chat memory + refusal

**Files:**
- Create: `backend/app/rag/retrieve.py`, `generate.py`, `backend/app/agents/memory.py`, `backend/app/services/llm.py`, `backend/app/services/metrics.py`, `backend/app/api/chat.py`
- Create: `backend/tests/unit/test_retrieve_ranking.py`, `backend/tests/unit/test_metrics.py`, `backend/tests/integration/test_chat_citations.py`

**Interfaces:**
- Consumes: Qdrant store, Embedder, chat session entities
- Produces:
  - `hybrid_retrieve(query, k=5, dense_weight=0.7) -> list[RetrievedChunk]`
  - `generate_answer(query, chunks, history) -> Answer(text, citations, refused: bool, usage)`
  - `POST /chat/sessions` → session id
  - `POST /chat/sessions/{id}/messages` `{content, mode?: "rag"|"agent"}` default `"rag"`
  - Response includes `answer`, `citations[{chunk_id, source, quote}]`, `metrics{latency_ms, prompt_tokens, completion_tokens}`
  - Refusal when no chunk above score threshold or model returns insufficient evidence

- [ ] **Step 1: Unit test ranking merge of dense + sparse scores**

```python
def test_hybrid_merge_prefers_agreement():
    dense = [("a", 0.9), ("b", 0.2)]
    sparse = [("a", 0.8), ("c", 0.7)]
    merged = merge_hybrid(dense, sparse, dense_weight=0.7, k=2)
    assert merged[0][0] == "a"
```

- [ ] **Step 2: Implement retrieve + metrics logger**

Log structured JSON: `query_id`, `retrieved_ids`, `scores`, `latency_ms`, `token_usage`, `cost_usd_estimate`.

- [ ] **Step 3: Implement generate with citation prompt; refuse if empty retrieval**

System rule: if retrieval empty or max score < threshold, return refused answer: "I don't know based on the knowledge base." with empty citations - never invent policy.

- [ ] **Step 4: Chat API + memory persistence (last N turns in Postgres; optional Redis cache of session)**

- [ ] **Step 5: Integration test with fixture doc ingested via HashEmbedder + mocked LLM returning cited stub**

Mock LLM in tests so CI needs no API key. Real keys used in manual demo.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: hybrid RAG chat with citations, memory, and refusal"
```

---

### Task 5: LangGraph agent + tools + HITL tickets

**Files:**
- Create: `backend/app/agents/tools.py`, `graph.py`, `backend/app/api/tickets.py`
- Create: `backend/tests/integration/test_agent_escalate.py`
- Modify: `backend/app/api/chat.py` to route `mode=agent`

**Interfaces:**
- Consumes: `hybrid_retrieve`, ticket repo, stub order lookup
- Produces tools:
  - `search_knowledge(query: str) -> str`
  - `lookup_order(order_id: str) -> dict` (stub dict; env `ORDER_API_URL` optional later)
  - `create_ticket(reason: str, priority: str) -> ticket_id` and pause for HITL when policy says escalate
- Graph nodes: `assistant` → `tools` → `assistant` → optional `hitl` → `finalize`
- `GET /tickets`, `POST /tickets/{id}/resolve` `{decision: "approve"|"reject", note?}`
- Chat response may include `ticket_id` and `status: "awaiting_human"`

- [ ] **Step 1: Write integration test - order not found → create_ticket → awaiting_human**

```python
def test_agent_escalates_when_order_missing(auth_client, monkeypatch):
    monkeypatch.setenv("ORDER_STUB_MODE", "miss")
    # send agent message asking about order ORD-404
    # assert response status awaiting_human and ticket exists
```

- [ ] **Step 2: Implement tools + LangGraph graph with interrupt/HITL pattern supported by current LangGraph API**

Keep graph code small and commented at node boundaries for interview narration.

- [ ] **Step 3: Wire tickets API + chat agent mode**

- [ ] **Step 4: Tests PASS without live LLM by mocking the model node**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: LangGraph support agent with tools and HITL tickets"
```

**Ownership gate B (Nate):** Narrate the graph node-by-node for failed `lookup_order` → `create_ticket` → human resolve.

---

### Task 6: Draft-reply API + n8n workflow export

**Files:**
- Create: `backend/app/api/drafts.py`, `n8n/workflows/draft-reply.json`
- Create: `backend/tests/integration/test_draft_reply.py`

**Interfaces:**
- Consumes: RAG generate pipeline (reuse)
- Produces: `POST /drafts/reply` with header `X-N8N-Secret`  
  Body: `{subject, body, customer_email?}` → `{draft, citations, refused}`  
  n8n flow: Webhook → HTTP Request to API → Slack/Email node (Slack webhook URL from env)

- [ ] **Step 1: Failing test - unauthorized without secret; authorized returns draft shape**

- [ ] **Step 2: Implement endpoint + shared secret check**

- [ ] **Step 3: Export n8n workflow JSON documented in README (import steps)**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: draft-reply API and n8n webhook workflow"
```

**Ownership gate C (Nate):** Walk ticket email → n8n → draft → Slack approve without opening admin.

---

### Task 7: Vite admin UI (login, docs, chunks, chat, tickets)

**Files:**
- Create: entire `web/` Vite + React + TypeScript app using fetch client + JWT in memory/localStorage
- Pages listed in file structure

**Interfaces:**
- Consumes: all REST endpoints from Tasks 2-6
- Produces: usable admin for demo; `npm run build` outputs static files served by Nginx

- [ ] **Step 1: Scaffold Vite React TS; API client with `Authorization: Bearer`**

- [ ] **Step 2: Login + Documents upload + Chunks table + Chat with citation list + Tickets resolve**

Keep UI minimal - no design-system rabbit hole. Clear labels beat polish.

- [ ] **Step 3: `docker-compose` service `web` builds and Nginx serves `/` → web, `/api` → api proxy (or API on subdomain documented)

- [ ] **Step 4: Manual smoke checklist in README**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: Vite admin for ingest, chunk inspect, chat, and tickets"
```

---

### Task 8: Expo React Native thin client

**Files:**
- Create: `mobile/` Expo app (TypeScript) with Login, Chat (citations), Tickets screens
- Configure `EXPO_PUBLIC_API_URL` for local and prod VPS

**Interfaces:**
- Consumes: same auth + chat + tickets APIs
- Produces: Expo Go-demoable app; no offline RAG

- [ ] **Step 1: `npx create-expo-app` (TS template) in `mobile/`**

- [ ] **Step 2: API client + Login + Chat screens showing citations and HITL banner**

- [ ] **Step 3: Ticket approve/reject screen**

- [ ] **Step 4: Document Expo Go demo steps in README**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: Expo mobile client for chat citations and HITL"
```

**Ownership gate D (Nate):** Demo phone → VPS path; explain why AI stays on server.

---

### Task 9: Evals harness + chunking experiment + Claude provider path

**Files:**
- Create: `backend/evals/golden_set.json`, `run_eval.py`, `chunking_experiment.py`
- Create: `docs/portfolio/chunking-decision-record.md` (template filled by script output)
- Modify: `backend/app/services/llm.py` for `LLM_PROVIDER=openai|anthropic`
- Create: `backend/tests/unit/test_metrics.py` extensions for cost estimate

**Interfaces:**
- Consumes: ingest + retrieve (+ optional generate)
- Produces: CLI  
  `python -m evals.run_eval` → prints hit_rate@k, recall@k, refusal rate, latency p50/p95, est. cost  
  `python -m evals.chunking_experiment` → compares `fixed|heading|parent_child` on golden set and writes markdown table into decision record

Golden set: start with 20-30 Qs over `sample_policy.md` + 1-2 extra fixtures; expand when real SMB docs arrive.

- [ ] **Step 1: Define golden JSON schema `{id, question, relevant_section_substrings[], should_refuse}`**

- [ ] **Step 2: Implement metrics + experiment runner (HashEmbedder or real embeddings behind flag)**

- [ ] **Step 3: Wire Anthropic provider selectable by env; one integration smoke with mock**

- [ ] **Step 4: Run experiment locally; paste results into `chunking-decision-record.md`**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: eval harness, chunking experiment, and Claude provider path"
```

**Ownership gate E (Nate):** Using the decision record, answer "How did you choose chunking?" with recall@k / hit_rate numbers.

---

### Task 10: Prod Compose on VPS + portfolio docs + harden

**Files:**
- Create/modify: `deploy/docker-compose.prod.yml`, `deploy/nginx.conf`, `docs/portfolio/architecture.md`, `jd-qa.md`, `aws-portability.md`, root `README.md`
- Harden: rate limit middleware (simple Redis token bucket), request timeouts, max upload size

**Interfaces:**
- Consumes: full stack
- Produces: documented VPS deploy; portfolio answers for Upwork Q1-Q5 grounded in this repo

- [ ] **Step 1: Prod compose + Nginx TLS notes (certbot) + `.env.example` complete**

- [ ] **Step 2: Rate limit chat/draft endpoints via Redis**

- [ ] **Step 3: Write architecture.md, jd-qa.md, aws-portability.md, polish README**

- [ ] **Step 4: CI green on unit + integration (mocked LLM)**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: VPS prod compose, hardening, and portfolio documentation"
```

**Ownership gate F (Nate):** Mock interview using `jd-qa.md` without reading code.

---

### Task 11: Real-user prep pack (not full partner acquisition)

**Files:**
- Create: `docs/portfolio/pilot-checklist.md` (what to ask SMB for; sample outreach; success metric)
- Create: `backend/evals/golden_set.partner.template.json`

**Interfaces:**
- Produces: checklist Nate uses to onboard first external user after deploy

- [ ] **Step 1: Write pilot checklist (docs needed, 10 seed questions, privacy note)**

- [ ] **Step 2: Commit**

```bash
git commit -m "docs: add SMB pilot onboarding checklist"
```

---

## Parallelism guide (for subagent-driven day)

Safe parallel after Task 1-2 land:

- Track A: Tasks 3 → 4 → 5 → 6 (backend AI path - keep serial)
- Track B: Task 7 (web) once Task 4 API shapes exist (can stub)
- Track C: Task 8 (mobile) parallel with Task 7
- Track D: Task 9 after Task 4
- Track E: Task 10 after A+B basic smoke
- Task 11 anytime after Task 10 docs exist

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Ingest PDF/MD + crawl | 3 |
| Chunking fixed/heading/parent-child + decision record | 3, 9 |
| Hybrid RAG + citations + memory + refusal | 4 |
| LangGraph tools + HITL | 5 |
| n8n draft workflow | 6 |
| FastAPI + Postgres + Redis + Qdrant | 1-4 |
| Vite admin + Expo RN | 7, 8 |
| Evals + cost/latency + Claude path | 9 |
| VPS Docker/Nginx/CI + AWS portability note | 1, 10 |
| Portfolio JD Q&A + architecture | 10 |
| Real external user path | 11 (+ Nate outreach) |
| Ownership / no black-box learning | Gates A-F |

No LlamaIndex in MVP (per constraints). AWS is documentation-only. Pinecone not required.

---

## Definition of done (code day)

- [ ] `docker compose -f deploy/docker-compose.yml up` runs API + deps locally
- [ ] Admin can upload MD, inspect chunks, chat with citations
- [ ] Agent mode can escalate to ticket; human resolve works
- [ ] n8n workflow JSON imports and calls `/drafts/reply`
- [ ] Expo app chats against API
- [ ] Eval + chunking experiment scripts run and decision record has numbers
- [ ] CI green
- [ ] Portfolio docs present
- [ ] Nate completed ownership gates A-F (learning bar)
