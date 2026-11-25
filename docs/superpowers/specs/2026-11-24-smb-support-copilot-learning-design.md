# SMB Support Knowledge Copilot - Learning & Build Design

Date: 2026-11-24  
Status: Approved design; implementation plan exists  
Owner: Nguyễn Văn Nhật  
Target job shape: Upwork-style RAG / AI agent / automation engineer roles  
Plan: `docs/superpowers/plans/2026-11-24-smb-support-copilot.md`

## 1. Purpose

Build one production-shaped LLM application end to end so the primary outcome is durable skill, not passive reading.
The same system must be strong enough for a resume, live demo, and interview defense.
It should also serve at least one real external user.

Skills must transfer to other RAG and agentic systems, not only this vertical.
Theory (especially Chip Huyen *AI Engineering*) is paired to each build phase, not binge-read up front.

Agents may scaffold and implement most of the codebase quickly.
That is encouraged.
The non-negotiable rule is that Nate must still own every subsystem cold (explain, debug, and defend it in interviews).
Code speed and mastery cadence are tracked separately.

## 2. Constraints and starting point

### Baseline

- Strong full-stack background (Node/Express, React, Postgres, Redis, some Golang/Mongo).
- Python scripting and automation experience (Scrapy, AWS EC2, Whisper pipelines on Upwork).
- Gap vs target JD: FastAPI-style Python AI backends, RAG, LangGraph agents, vector DBs, evals, shipping a live LLM product.

### Time and success bar

Separate **agent build time** from **human mastery time**:

| Track | Cadence | Meaning |
|-------|---------|---------|
| Agentic implementation | About 1 dense day (or 2 short sessions) for MVP code per the implementation plan | Scaffold, wiring, tests, clients, Compose, eval scripts |
| Ownership gates | Same day or next session after each major slice | Nate explains chunking, RAG, graph, n8n, deploy path aloud |
| Theory (Chip Huyen + docs) | Task-scoped bites when a gate or bug needs them | Not a multi-week reading prelude |
| Real user + interview polish | Days to a few weeks after MVP runs | Partner docs, retrieval fixes, demo video, mock interviews |

- Nate availability still assumes aggressive focus (~20+ hrs/week) when polishing, onboarding a user, and drilling interviews.
- Success requires all of:
  - Public live app (API + admin) and React Native demo.
  - GitHub + write-up that answers the target JD application questions from this system.
  - Ability to pass a deep mock interview on architecture, chunking, retrieval, agents, cost, and failure modes.
  - At least one real external user or small business using it (even unpaid).

### Deploy constraint

- Live deployment uses the existing **VPS** (Docker + Nginx + GitHub Actions).
- AWS is documented as a portable mapping of the same stack for clients who require it, not a paid MVP requirement.

## 3. Product

### What it is

An **SMB Support Knowledge Copilot** for internal support/ops staff at one small business.

Staff ask questions against the business's own documents and FAQs.
The system answers with citations.
For action-oriented requests it can call tools or escalate to a human.
n8n connects inbound tickets/emails to draft replies for human approval.

### Clients

- **Web admin:** ingest, inspect chunks/sources, chat, basic ticket/HITL views.
- **React Native (Expo):** login, chat with citations, tool/HITL status, approve/reject drafts when in scope.
- All RAG/agent logic stays on the server.
- Mobile is a thin client for resume demo value (~20% of effort vs ~70% backend/AI and ~10% web admin).

### MVP in scope

1. Document ingest (PDF, Markdown) and small website/FAQ crawl.
2. Chunk, embed, store in a vector DB with clear lineage metadata.
3. RAG chat with hybrid retrieval, citations, conversation memory, and safe refusal.
4. LangGraph agent with tools: `search_knowledge`, `lookup_order` (stub then real/simple API), escalate / create ticket (HITL).
5. n8n workflow: webhook inbound → API draft reply → Slack/email for human approve.
6. FastAPI backend, Postgres, Redis.
7. Dockerized deploy on VPS with CI.
8. Eval harness on a small golden set (retrieval, faithfulness, latency, cost).
9. Portfolio pack: README, architecture, chunking decision record, JD Q&A sheet, short demo video.

### Explicitly out of MVP

- Multi-tenant SaaS (design boundaries so a later upgrade is possible).
- Fine-tuned models.
- Offline on-device RAG.
- WordPress/Drupal plugins (roadmap mention only).
- Multi-agent swarms beyond one orchestrated LangGraph.
- App Store polish beyond a reliable Expo demo build.
- Full CRM replacement.

### First real user

One concrete partner (shop, clinic, agency, or friend's business) with real docs.
Free pilot.
Success signal: drafts or answers that save them time.

## 4. Architecture

```text
[React Native] ──┐
                 ├──► FastAPI (auth, chat, ingest, tickets)
[Web admin]   ──┘         │
                          ├──► RAG pipeline (chunk → embed → hybrid retrieve → generate)
                          ├──► LangGraph agent (tools + memory + HITL gates)
                          ├──► Postgres (users, sessions, tickets, eval runs)
                          ├──► Redis (rate limit / job queue / short-term cache)
                          ├──► Vector DB (chunks + embeddings)
                          └──► LLM APIs (primary + fallback provider)
                                │
[n8n] ◄──webhooks/REST─────────┘  (ticket in → draft out → Slack/email)
```

### Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| API | FastAPI + async Python | Matches JD; closes the main backend gap |
| Orchestration | LangGraph (+ LangChain pieces as needed) | Agents, tools, HITL, interview relevance |
| Extra RAG kit | LlamaIndex only if ingest/eval clearly benefits; not a second full stack in MVP | Avoid framework sprawl |
| Vector DB | Qdrant (Docker on VPS) | JD-listed, self-hosted, cost-friendly for learning |
| LLMs | OpenAI primary; Anthropic Claude as second provider on one path (Gemini optional stretch) | Multi-provider story without boiling the ocean |
| Data | Postgres + Redis | Familiar; sessions, tickets, metadata, cache/queue |
| Automation | n8n | JD requirement; keep workflows thin |
| Mobile | Expo React Native | Fast demo; reuses React skill |
| Web | Vite + React admin (Nginx-served static) | Thin admin UI; simple on VPS next to FastAPI; RN remains the mobile demo |
| Deploy | Docker + Nginx on existing VPS + GitHub Actions | Live without extra AWS spend |
| Observability | Structured logs + latency/cost metrics; LangSmith optional later | Interviewable ops story |

### Happy-path data flow

1. Admin uploads a doc or triggers a crawl.
2. Worker normalizes text, chunks, embeds, upserts into Qdrant with lineage.
3. User asks via RN or web.
4. API loads session memory, hybrid-retrieves, optionally reranks, generates cited answer.
5. If intent needs action, LangGraph runs tools; low confidence or policy triggers HITL.
6. External ticket hits n8n; n8n calls `/draft-reply`; human approves in Slack/email.

### Errors and safety (MVP)

- Retrieval miss → refuse or "I don't know"; do not invent policy.
- Tool/API failure → clear message + ticket fallback.
- Auth on mutating routes; single-business tenant in v1.
- Per-request token/cost caps and timeouts.

### Testing

- Unit: chunkers, prompt builders, tool schemas.
- Integration: retrieve → answer on golden docs.
- Eval suite: relevance, faithfulness, latency, cost.
- E2E: scripted chat path + one n8n webhook path; RN smoke on critical screens.

## 5. RAG design and chunking strategy

Chunking is a first-class design topic because it is a common interview failure mode and a real quality lever.

### Ingestion

- Sources: PDF, Markdown, FAQ pages, small site crawl.
- Normalize text while preserving headings and lists when possible.
- Persist raw documents (Postgres and/or object storage on VPS).
- Store chunks + embeddings in Qdrant with metadata: `doc_id`, `source_url`, `page`/`section`, `version`, `doc_type`, filters such as product/language/`updated_at`.

### Chunking approach

Prefer **structure-aware + parent-child**, validated by evals - not a single magic number.

1. **Structure first:** split on headings/sections when present so policies stay coherent.
2. **Size second:** target about 400-800 tokens per chunk; overlap about 10-15%; tune with evals.
3. **FAQ atomicity:** often one chunk per question (+ short answer context).
4. **Parent-child:** small child chunks for precise retrieval; attach parent section into LLM context for coherence.
5. **Metadata filters** before or with hybrid ranking.
6. **Re-chunk on update:** version bump, delete old vectors, re-embed; never mix versions silently.

### Experiment mandate (portfolio artifact)

Compare at least:

- Fixed-size chunking.
- Heading/section-based chunking.
- Parent-child retrieval.

Record recall@k / hit rate, faithfulness or citation correctness, and qualitative failure examples.
Keep the winner for the partner corpus and document why.

### Interview answer shape

"I did not pick a magic number.
I started structure-aware, used parent-child, then ran a golden set comparing fixed-size vs heading-based vs parent-child on recall@k and faithfulness, and kept the winner for this corpus."

### Retrieval and generation

- Hybrid: dense embeddings + sparse/keyword (BM25-style or Qdrant sparse).
- Optional reranker only if evals justify it.
- Answers must cite sources; low confidence → refuse or escalate.
- Log query, retrieved ids, scores, tokens, latency, cost.

### Optimization loop

Small golden set (about 30-50 questions from the real user's docs).
Change one variable at a time (chunk size, overlap, hybrid weights, prompt).
Re-measure retrieval hit rate, citation correctness, faithfulness, p95 latency, and cost per answer.

## 6. Learning and build roadmap

Implementation order and file-level tasks live in the plan (`docs/superpowers/plans/2026-11-24-smb-support-copilot.md`).
Agents execute that plan at coding speed.
The phases below are **ownership slices**, not week-long coding estimates.

Rule per slice: thin theory bite when blocked + build/land the slice + "explain aloud" gate.
No binge-reading.
Do not treat a slice as mastered until the gate passes, even if the code already merged.

### Phase 0 - Foundations (plan Tasks 1-2, 8 smoke)

- Build: FastAPI skeleton, Compose (Postgres/Redis/Qdrant), CI healthcheck, Expo hitting health.
- Read: Chip Huyen productizing/eval overview as orientation; FastAPI async only as needed.
- Gate: whiteboard phone → VPS → DB path.

### Phase 1 - Ingest + chunking lab (plan Task 3 + experiment in Task 9)

- Build: upload PDF/MD + simple crawl; fixed vs heading vs parent-child chunkers; embed to Qdrant; admin inspect UI.
- Read: Chip Huyen data/RAG chapters; chunking docs; parent-document retriever reference.
- Gate: explain chunking winner with numbers on a sample corpus.

### Phase 2 - RAG chat with citations (plan Tasks 4, 7-8 chat surfaces)

- Build: hybrid retrieve → generate with citations + memory; RN/web chat; refusal behavior.
- Read: Chip Huyen retrieval/prompt chapters; tool/function calling overviews as needed.
- Gate: demo golden questions with citation proof; know failure modes.

### Phase 3 - Agent + HITL (plan Task 5)

- Build: LangGraph with `search_knowledge`, `lookup_order` (stub), escalate/create ticket; structured outputs; HITL pause.
- Read: LangGraph docs for graphs/tools/HITL only as used; Chip Huyen agent sections.
- Gate: narrate graph node-by-node for failed lookup → escalate.

### Phase 4 - n8n workflow (plan Task 6)

- Build: webhook → `/draft-reply` → Slack/email approve; one realistic inbound source.
- Read: n8n webhook/HTTP docs as needed.
- Gate: ticket → draft → human approve without opening admin.

### Phase 5 - Evals, cost, harden (plan Tasks 9-10)

- Build: golden harness; latency/cost logs; rate limits; auth; refusal tests; Claude provider path; VPS prod compose.
- Read: Chip Huyen evaluation and system-design chapters; simple custom metrics before optional RAGAS.
- Gate: answer JD evaluation/hallucination/cost question from your own metrics.

### Phase 6 - Real user + portfolio (plan Task 11 + Nate outreach)

- Build: onboard partner docs; fix retrieval gaps; RN demo polish; portfolio write-up; mock interview.
- Read: only gaps that block production issues.
- Gate: live URL + Expo demo + one external user result.

### Resource policy

- Primary book: Chip Huyen *AI Engineering*, chapter when it unblocks a gate or bug.
- Primary docs: LangGraph, Qdrant, FastAPI, Expo - task-scoped.
- Avoid: hoarding courses; dual full frameworks in MVP.

## 7. Portfolio and interview defense

### Artifacts

1. Live API + web admin on VPS; Expo RN demo (TestFlight/internal, Expo Go, and/or recorded walkthrough).
2. GitHub: README, architecture diagram, VPS setup, `.env.example` (no secrets).
3. JD answer sheet for the five application questions, grounded in this system.
4. Chunking decision record with experiment table.
5. Two-to-three minute demo video: ingest → cited mobile chat → agent/HITL → n8n draft.

### Must-answer cold

- Why thin clients and server-side AI.
- Chunking strategy and evidence.
- Hybrid retrieval, citations, refusal.
- LangGraph nodes, tools, HITL.
- Quality, cost, latency measurement and next changes.
- How the same compose stack maps to AWS if a client requires it.

### Definition of done

| Bar | Measure |
|-----|---------|
| Live | Public URL healthy; RN chat works against prod API |
| Skills | Can teach Phases 1-5 in a mock interview |
| Real user | ≥1 external user with their docs; qualitative win |
| JD-ready | Proposal draft ("RAG AI Engineer") + repo/live/demo links |
| Transfer | Doc lists domain-specific vs reusable RAG/agent pieces |

### Risk controls

- Mobile scope creep → thin client only.
- Framework sprawl → LangGraph primary.
- No partner soon after MVP deploy → willing friend's business docs still count as external.
- VPS limits → async/queue heavy ingest; keep eval corpus small.

## 8. Mapping to target job description

| JD expectation | Coverage in this project |
|----------------|--------------------------|
| Production RAG + vector DB | Qdrant + hybrid retrieve + citations |
| Document ingest + semantic/hybrid QA | PDF/MD/crawl + chunking lab + chat |
| AI agents, tools, HITL, memory | LangGraph agent path |
| Multi-provider LLMs | OpenAI + Claude or Gemini path |
| n8n / webhooks / automation | Draft-reply workflow |
| FastAPI Python backend | Core API |
| Postgres / Redis | System of record + cache/queue |
| Docker + CI (+ cloud story) | VPS Docker/Nginx/Actions; AWS as portability note |
| Evals, hallucination, cost, latency | Golden set + logging + decision records |
| Live demo + repos | Explicit portfolio artifacts |
| Support / ecom / CRM-adjacent | SMB support vertical |

## 9. Next step

Implementation plan is written: `docs/superpowers/plans/2026-11-24-smb-support-copilot.md`.
Execute it with subagent-driven or inline plan execution.
Land ownership gates A-F from that plan as the learning definition of done alongside working software.

## 10. Non-goals for the learning process

- Shipping agent-generated code without passing ownership gates (black-box portfolio).
- Collecting certificates instead of a running system.
- Expanding into unrelated AI topics before the MVP definition of done is met.
- Treating slow human typing estimates as a constraint on agent implementation speed.
