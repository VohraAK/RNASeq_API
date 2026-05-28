# RNA-Seq DEG Analysis API

A production-grade web API for RNA-Seq Differential Expression Gene (DEG) analysis. Built as part of a Directed Research Project in Computational Biology.

Wraps [PyDESeq2](https://github.com/owkin/PyDESeq2) behind a secure, async REST API — making DEG analysis accessible over HTTP to both browser users and automated pipelines.

---

## Stack

| Layer | Choice |
|---|---|
| API | FastAPI + uvicorn |
| Database | PostgreSQL |
| Task queue | procrastinate (PostgreSQL-backed) |
| Auth | JWT HS256 + API keys |
| Config | pydantic-settings |
| Rate limiting | slowapi |
| Reverse proxy | Caddy (auto HTTPS) |
| Containers | Docker Compose |

---

## Architecture

**Three-tier:**
- **API process** — handles HTTP, auth, validation, routing. Never runs analysis directly.
- **Worker process** — picks up jobs from procrastinate queue, runs `DESeqEngine`, writes results to DB.
- **PostgreSQL** — stores all relational data and doubles as the task queue broker.

DESeq2 fitting is CPU-bound and takes minutes. Offloading it to a worker process keeps the API responsive.

**Job lifecycle:** `QUEUED → RUNNING → COMPLETED | FAILED`. Cancel allowed on `QUEUED` only.

---

## API

All routes under `/api/v1/`. Every response uses a consistent envelope:

```json
{ "data": { ... }, "meta": { "page": 1, "total": 24531 } }
{ "error": { "code": "JOB_NOT_FOUND", "message": "..." } }
```

| Router | Routes |
|---|---|
| `/auth` | register, login, refresh, logout |
| `/users` | profile, API key CRUD |
| `/files` | upload counts/metadata CSVs |
| `/jobs` | submit, poll, cancel |
| `/results` | paginated DEG table, volcano plot, MA plot |
| `/health` | liveness check (no auth) |

Interactive docs: `http://localhost:8000/api/docs`

---

## Auth

- **JWT** — 15-min access token (`Authorization: Bearer`), 7-day rotating refresh token (httpOnly cookie). For browser users.
- **API keys** — `rnaseq_sk_<64 hex>`, SHA-256 hashed, shown once, 90-day expiry, max 10 per user. For scripts/services.
- Both accepted on all protected routes via a unified `get_current_user` dependency.

---

## Running Locally

```bash
# copy and fill in secrets
cp .env.example .env

# start all services
docker compose up -d

# run DB migrations
docker compose exec api alembic upgrade head

# follow logs
docker compose logs -f api
docker compose logs -f worker
```

API available at `http://localhost:8000`. Caddy proxies HTTPS at `https://localhost`.

---

## Input Format

| File | Format |
|---|---|
| Counts matrix | CSV, rows = genes, columns = samples, **raw integer counts only** |
| Metadata | CSV, rows = samples, columns = covariates, sample names must match counts columns exactly |

Files are validated at upload — format errors surface immediately, not after queuing.

---

## Data Retention

- Jobs + results: deleted 14 days after completion
- Uploaded files: purged at expiry if not attached to a job
- Cleanup runs nightly via procrastinate scheduler

---

## Security

- Rate limits: 100 req/min/IP global, 10 jobs/hour/user, 20 uploads/hour/user, 10 auth attempts/15min/IP
- File upload cap: 100MB
- Design formula validated against Wilkinson notation regex before execution
- CORS explicit allowlist (`ALLOWED_ORIGINS` env var)
- Raw exceptions never returned to clients

---

## Testing

```bash
# unit tests (no Docker required)
python -m pytest tests/ -v
```

39 tests across auth service, storage service, and analysis wrapper. DESeqEngine mocked via `sys.modules` injection.

---

## Environment Variables

See `.env.example` for all required variables. Key ones:

```
DATABASE_URL=postgresql+asyncpg://...
SECRET_KEY=<64 char hex>
ALLOWED_ORIGINS=http://localhost:3000
UPLOAD_DIR=/var/rnaseq/uploads
```

---
## API Swagger Docs
![API Docs](/assets/api-doc.png)