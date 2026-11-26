# SMB Support Knowledge Copilot

An AI-assisted knowledge and support workspace for small and medium businesses.
Upload documents or crawl a site, then ask questions and get answers with verified citations, or a refusal when the knowledge base has no evidence.
An agent mode escalates risky requests to a human through tickets, and an n8n workflow drafts replies for Slack review.

Stack: FastAPI, Postgres, Qdrant, Redis, LangGraph, OpenAI or Claude, a Vite admin UI, an Expo mobile client, Docker Compose, and Nginx.

## Documentation

- [Architecture](docs/portfolio/architecture.md): flows, diagrams, hardening, and deployment.
- [Chunking decision record](docs/portfolio/chunking-decision-record.md): eval-backed chunking choice.
- [Interview Q&A](docs/portfolio/jd-qa.md): answers grounded in this repo.
- [AWS portability](docs/portfolio/aws-portability.md): how this VPS design would map to AWS (documentation only).
- [Pilot onboarding checklist](docs/portfolio/pilot-checklist.md): prep pack, privacy note, and seed questions for the first external SMB user.

## Local development

Requirements:

- Docker with Compose
- Python 3.12 for backend development

Start the local stack:

```bash
cp .env.example .env
docker compose --env-file .env -f deploy/docker-compose.yml up --build
```

The admin UI is served at `http://localhost`.
Nginx serves `/` from the `web` service and proxies `/api/*` to the API with the `/api` prefix stripped.
The API is also available directly at `http://localhost:8000`.
Check it with:

```bash
curl http://localhost:8000/health
curl http://localhost/api/health
```

## Admin UI (web/)

Requires Node 22.
For hot-reload development, run the API on port 8000 and start Vite, which proxies `/api` to it:

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173` (already in the default `CORS_ORIGINS`).
`npm run build` writes static files to `web/dist`.
Set `VITE_API_URL` at build time to call an API on another origin instead of `/api`.

The API has no list-documents endpoint, so the Documents page remembers documents ingested from this browser in localStorage.
To inspect chunks of any other document, paste its ID on the Chunks page.

### Manual smoke checklist

1. Open `http://localhost`, register a new user (password of at least 8 characters), and confirm the Documents page appears.
2. Reload the page and confirm you stay logged in; log out and log back in.
3. Upload `backend/evals/fixtures/sample_policy.md` and confirm it appears in the table with a chunk count above zero.
4. Crawl a public URL and confirm a second row appears.
5. On Chunks, load the uploaded document and confirm chunk content, section, and strategy columns render.
6. On Chat in RAG mode, ask a question covered by the document and confirm the answer lists citations.
7. Ask an unrelated question and confirm the answer is marked as refused.
8. Switch to Agent mode and ask for something needing human review (for example a refund request) and confirm a ticket ID is shown.
9. On Tickets, confirm the ticket is open, then Approve or Reject it and confirm the status changes.

Run backend tests:

```bash
cd backend
python -m pip install -e ".[dev]"
pytest
```

To run integration tests against the Compose Postgres service, set `DATABASE_URL` to a dedicated test database before invoking pytest:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:dev-only-change-me@localhost:5432/copilot_test pytest
```

When `DATABASE_URL` is not explicitly set, the auth smoke test uses a temporary SQLite database so the test suite can run without Docker.

## Mobile client (mobile/)

An Expo (SDK 58, React Native, TypeScript) thin client with Login, Chat, and Tickets screens.
It only calls the same HTTP API as the admin UI.
Retrieval, embeddings, the LLM, and the agent all stay on the server, so there is no on-device RAG and no offline mode.
This keeps API keys and the knowledge base off the phone and means web and mobile always behave the same.

Node: Expo SDK 58 supports Node `^22.13.0 || ^24.3.0 || >=26.0.0`, declared in `mobile/package.json` `engines`.
Node 22 (preferred) and Node 26 both work; the iOS bundle was verified on Node 26.

### Expo Go demo

1. Start the API so the phone can reach it: `docker compose --env-file .env -f deploy/docker-compose.yml up --build` (the API listens on port 8000).
2. Install **Expo Go** on your phone and join the same Wi-Fi network as your computer.
3. Find your computer's LAN IP (for example `ipconfig getifaddr en0` on macOS).
   `localhost` does not work from a phone because it points at the phone itself.
4. Configure and start the app:

   ```bash
   cd mobile
   cp .env.example .env.local
   # edit .env.local: EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8000
   npm install
   npx expo start
   ```

5. Scan the QR code with the Camera app (iOS) or Expo Go (Android).
6. Register or log in, ask a question in RAG mode and check the citations, then switch to Agent mode and ask for a refund to see the "Awaiting human review" banner.
7. Open the Tickets tab, then Approve or Reject the ticket.

To demo against the VPS, set `EXPO_PUBLIC_API_URL` to the public API URL (for example `https://api.example.com`) and restart with `npx expo start -c`.
Expo inlines `EXPO_PUBLIC_*` values at bundle time, so changing them requires a restart.
Plain `http://` URLs to non-localhost hosts work in Expo Go for demos; use HTTPS for any real deployment.

Typecheck with `npm run typecheck`.

## Evals and chunking experiment

The golden set lives in `backend/evals/golden_set.json` and runs against the fixtures in `backend/evals/fixtures/`.
No Postgres, Qdrant server, or API key is needed: the harness uses SQLite, in-memory Qdrant, and `HashEmbedder` by default (`aiosqlite` comes with the `dev` extra).

```bash
cd backend
PYTHONPATH=. python -m evals.run_eval --llm mock          # hit_rate@k, recall@k, refusal rate, latency p50/p95, est. cost
PYTHONPATH=. python -m evals.chunking_experiment          # rewrites the table in docs/portfolio/chunking-decision-record.md
```

Use `--embedder openai` for real embeddings and `--llm configured` to call the configured model.
See `docs/portfolio/chunking-decision-record.md` for the results and the chunking decision.

## LLM provider

Set `LLM_PROVIDER=openai` (default, uses `LLM_MODEL`) or `LLM_PROVIDER=anthropic` (uses `ANTHROPIC_MODEL` and `ANTHROPIC_API_KEY`).
The Claude path calls the Anthropic Messages API directly and shares the same citation verification and refusal rules as OpenAI.

## Rate limiting and hardening

Chat messages are limited per user and draft replies per n8n caller with a Redis token bucket.
Tune it with `RATE_LIMIT_CHAT_BURST`, `RATE_LIMIT_CHAT_PER_MINUTE`, `RATE_LIMIT_DRAFTS_BURST`, and `RATE_LIMIT_DRAFTS_PER_MINUTE`, or turn it off with `RATE_LIMIT_ENABLED=false`.
Exceeding a limit returns `429` with a `Retry-After` header.
If Redis is unreachable the limiter allows the request and logs a warning.

Other limits: uploads are capped at 10 MB, model calls time out after `LLM_TIMEOUT_SECONDS`, and `APP_ENV=production` makes the API refuse the default `JWT_SECRET` and hide `/docs`.

## Deploy to a VPS

Prerequisites: a Linux VPS with Docker and Compose v2.24 or newer, a DNS `A` record pointing your domain at the VPS, and ports 80 and 443 open.
This path uses Nginx and Let's Encrypt on the VPS itself, no cloud account needed.

1. Clone the repository on the VPS and create the environment file:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set at least:
   - `APP_ENV=production`
   - `JWT_SECRET` (`openssl rand -hex 32`)
   - `POSTGRES_PASSWORD` (a strong value)
   - `N8N_DRAFT_SECRET` (`openssl rand -hex 32`)
   - `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` with the matching `LLM_PROVIDER`
   - `DOMAIN` and `LETSENCRYPT_EMAIL`
   - `CORS_ORIGINS` (only needed for browser clients on other origins, the admin UI uses same-origin `/api`)

3. Issue the first certificate while nothing else is listening on port 80:

   ```bash
   docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml \
     run --rm -p 80:80 --entrypoint certbot certbot \
     certonly --standalone -d "$DOMAIN" -m "$LETSENCRYPT_EMAIL" --agree-tos --no-eff-email
   ```

   Export `DOMAIN` and `LETSENCRYPT_EMAIL` in your shell first, for example with `set -a; . ./.env; set +a`.

4. Switch renewals to the webroot method served by Nginx, then start the stack:

   ```bash
   docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
   docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml \
     run --rm --entrypoint certbot certbot \
     reconfigure --cert-name "$DOMAIN" --authenticator webroot --webroot-path /var/www/certbot
   ```

5. Verify:

   ```bash
   curl https://$DOMAIN/api/health
   docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml \
     run --rm --entrypoint certbot certbot renew --dry-run
   ```

How it fits together:

- `deploy/docker-compose.prod.yml` layers on the local file.
  It closes the Postgres, Redis, Qdrant, and API host ports, adds restart policies and log rotation, enables Redis persistence, adds an API health check, and runs a certbot renewal loop.
- `deploy/nginx.prod.conf` is rendered by the Nginx image with `DOMAIN`.
  It redirects HTTP to HTTPS, serves ACME challenges, terminates TLS, sets security headers, limits `/api/auth/*` to 10 requests per minute per IP, and caps request bodies at 11 MB.
- Nginx reloads every 6 hours so renewed certificates are picked up without downtime.
- Update with `git pull` followed by the same `up -d --build` command.
- Back up the `postgres_data` and `qdrant_data` volumes.
  The schema has no migrations yet, see the next section before upgrading.

For the mobile app set `EXPO_PUBLIC_API_URL=https://$DOMAIN/api`.
For n8n set `DRAFT_API_URL` to the internal API address if n8n joins the Compose network (`http://api:8000`), or to `https://$DOMAIN/api` otherwise.

## Database schema changes

Tables are created on API startup with SQLAlchemy `create_all`, which never alters tables that already exist.
There are no migrations yet.
After pulling a change that adds or changes model columns, reset the local Compose volumes so the tables and the Qdrant collection are recreated:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml down -v
docker compose --env-file .env -f deploy/docker-compose.yml up --build
```

This deletes all local data, including Postgres rows and Qdrant vectors.
Task 3 added `documents.source_type`, `documents.source_uri`, `documents.version`, `chunk_records.section`, `chunk_records.strategy`, and `chunk_records.qdrant_point_id`, so any database created before it needs this reset.

## n8n draft-reply workflow

The API exposes `POST /drafts/reply` for trusted n8n workflows.
Requests must send the shared `X-N8N-Secret` header and a JSON body containing `subject`, `body`, and an optional `customer_email`.
Set `N8N_DRAFT_SECRET` to the same strong random value in the API and n8n environments.

Set `DRAFT_USER_EMAIL` to the email of an existing application user whose uploaded documents should provide the draft's knowledge base.
The endpoint searches only documents owned by that user.
It returns a grounded `draft`, `citations`, and `refused`, matching the chat RAG pipeline's refusal behavior.

Import `n8n/workflows/draft-reply.json` from the n8n Workflows page.
Configure these environment variables for the n8n process:

- `DRAFT_API_URL`: API base URL, such as `http://api:8000`
- `N8N_DRAFT_SECRET`: shared secret configured on the API
- `SLACK_WEBHOOK_URL`: Slack incoming webhook URL for the approval channel

Activate the imported workflow, then send ticket data to its production webhook:

```bash
curl -X POST https://n8n.example.com/webhook/draft-reply \
  -H 'Content-Type: application/json' \
  -d '{"subject":"Refund request","body":"Can I get a refund?","customer_email":"customer@example.com"}'
```

The workflow forwards the ticket to the draft API and posts the grounded result to Slack for human review.
