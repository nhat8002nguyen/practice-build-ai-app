# AWS portability

This project runs on a single VPS with Docker Compose and Nginx.
Nothing here is deployed on AWS.
This document explains how each piece would map, so the design can be discussed honestly without paying for a cloud account.

## Why a VPS

A VPS keeps the monthly cost predictable and the whole stack reproducible with one Compose file.
The application is already containerized, stateless apart from its data stores, and configured by environment variables.
Those three properties are what make a move to AWS mostly a hosting change, not a rewrite.

## Component mapping

| Today (VPS) | AWS equivalent | Notes |
| --- | --- | --- |
| `api` container | ECS Fargate service behind an ALB | Same image, same env vars. Health check path is `/health`. |
| `web` container + Nginx static | S3 + CloudFront | `npm run build` output is static, so the web container is not needed. |
| Nginx TLS + certbot | ALB + ACM certificate | Removes the renewal loop. HSTS and `/api/auth` limits move to CloudFront or WAF rules. |
| Postgres container | RDS PostgreSQL or Aurora | Change `DATABASE_URL`. Needs backups and a migration tool first (see gaps). |
| Redis container | ElastiCache for Redis | Change `REDIS_URL`. The rate limiter uses one Lua `EVAL`, which ElastiCache supports. |
| Qdrant container | Qdrant Cloud, or Qdrant on EC2/ECS with EBS | Change `QDRANT_URL`. AWS has no managed Qdrant, OpenSearch or pgvector would be a different design. |
| `.env` file | Secrets Manager or SSM Parameter Store | Inject as ECS task secrets. Covers `JWT_SECRET`, API keys, `N8N_DRAFT_SECRET`. |
| json-file logs | CloudWatch Logs | Query metrics are already JSON log lines, so a CloudWatch Logs Insights query works without code changes. |
| GitHub Actions CI | GitHub Actions to ECR and ECS | Add a job that builds the image, pushes to ECR, and updates the service. |
| n8n | n8n on ECS, or n8n Cloud | Keep `DRAFT_API_URL` pointed at the internal API address. |

## What would have to change in code

- Migrations: tables are created with `create_all` on startup, which never alters existing tables.
  Alembic is needed before RDS holds data worth keeping.
- Agent checkpoints: `MemorySaver` loses paused runs when a task restarts or when a second task serves the resolve call.
  On ECS with more than one task, switch to the LangGraph Postgres saver.
- Ingestion: uploads and crawls run inside the request.
  Large documents would move to an SQS queue and a worker task.
- Rate limiter: no change, buckets are already shared through Redis, so every Fargate task sees the same state.
- Uploads: files are parsed in memory and not stored, so no S3 integration is required.

## Scaling notes

- The API is horizontally scalable once agent checkpoints are in Postgres.
- Retrieval computes BM25 per query over one user's chunks, which is fine at SMB scale.
  Past tens of thousands of chunks per user, move sparse search into a stored index.
- The LLM is the latency and cost driver.
  Per-query token usage and estimated cost are already logged, so alarms can be built from logs.

## Rough migration order

1. Move Postgres to RDS and Redis to ElastiCache, keep everything else on the VPS.
2. Move secrets to SSM.
3. Run the API on ECS behind an ALB with ACM.
4. Move the web build to S3 and CloudFront.
5. Retire the VPS.

Each step is independently reversible, because the API only sees connection strings.
