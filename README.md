# AgentFlow AI

Enterprise multi-agent customer operations platform for B2B SaaS.

A support ticket is decomposed into a deterministic LangGraph workflow executed
by specialised agents, with RAG-grounded knowledge, MCP-mediated enterprise
access, human-in-the-loop approval for risky actions, and a React operations
console.

`srs.md` is the authoritative specification.

**Status: all 8 phases complete.**

---

## What it does

A ticket such as *"I was charged twice for my enterprise subscription and my
dashboard is locked"* flows through:

```
POST /tickets ──▶ Redis stream ──▶ dispatcher
                                      │
                                      ▼
   supervisor ──▶ task planner ──▶ ┌ billing agent  ┐
  (classify)     (deterministic)   │ account agent  │ (parallel, plan-driven)
                                   └ technical agent┘
                                      │
                    policy agent ◀────┘        (LLM; verdict wins conflicts)
                         │
                 results aggregator             (deterministic)
                         │
                    risk engine                 (deterministic; owns risk_score)
                         │
              ┌──────────┴───────────┐
      requires_hitl               otherwise
              │                       │
      human approval ────────────────▶│         (interrupt; resumes on approval)
                                      ▼
                              response agent
                                      │
                                 dispatcher      (delivery; owns "completed")
```

Every node checkpoints to PostgreSQL, so a workflow survives a process restart
and resumes exactly where it paused.

---

## Architecture

| Layer | Responsibility |
|-------|----------------|
| **FastAPI** | HTTP only. Validates, queues, returns `202`. Never calls an LLM or MCP. |
| **LangGraph** | Orchestration. Owns `GraphState`, routing, checkpoints, interrupts. |
| **Agents** | Reasoning only. No SQL, no HTTP, no env vars, no agent-to-agent calls. |
| **Enterprise MCP** | The only path to enterprise data. 12 namespaced tools, every call audited. |
| **Qdrant** | Knowledge base for RAG. Retrieve before generating; say "insufficient information" rather than inventing. |
| **PostgreSQL** | Business data, checkpoints, audit logs. |
| **Redis** | Work queue and ephemeral runtime memory. Never permanent records. |

Three non-negotiable rules cut across the codebase:

1. **Reasoning is separate from execution.** LLMs decide, LangGraph controls
   flow, MCP performs I/O.
2. **GraphState is the single source of truth.** Nodes return update dicts and
   never mutate state in place. Fields written by parallel agents carry
   reducers.
3. **Every business action is auditable.** Approvals, conflicts, tool calls and
   workflow outcomes all leave rows in `audit_logs`.

### Services

| Service | Port | Role |
|---------|------|------|
| `frontend` | 3000 | Operations console (React + nginx) |
| `backend` | 8000 | REST API; runs migrations on boot |
| `enterprise-mcp` | 8001 | MCP tool server |
| `dispatcher` | – | Executes workflows; **the only service needing `GROQ_API_KEY`** |
| `postgres` | 5432 | Business data, checkpoints, audit |
| `redis` | 6379 | Workflow queue |
| `qdrant` | 6333 | Vector knowledge base |

---

## Quickstart

```bash
cp .env.example .env          # set GROQ_API_KEY to run real workflows
docker compose up --build
docker compose exec backend python -m scripts.seed_database
docker compose exec backend python -m scripts.ingest_knowledge
```

Then open the operations console at **<http://localhost:3000>**.

API docs are at <http://localhost:8000/docs>. Migrations run automatically when
the backend boots.

Without a `GROQ_API_KEY` everything starts and the API works, but a queued
workflow fails at the Supervisor — the dispatcher is the only service that
calls the LLM, so check its logs first if a ticket sits at `pending`:

```bash
docker compose logs -f dispatcher
```

### Local development

```bash
python -m venv .venv
.venv\Scripts\activate                    # source .venv/bin/activate on Unix
pip install -r requirements.txt
docker compose up -d postgres redis qdrant
alembic upgrade head
python -m scripts.seed_database
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend && npm install && npm run dev  # http://localhost:5173
```

The dev server proxies API paths to `localhost:8000`, so no CORS setup is
needed.

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/tickets` | Submit a ticket. Returns `202` immediately with a `workflow_id`. |
| `GET` | `/tickets` | List tickets with workflow state, tier and priority. |
| `GET` | `/tickets/{ticket_id}` | Ticket detail and resolution. |
| `GET` | `/workflows` | List workflow runs. |
| `GET` | `/workflows/{workflow_id}` | Workflow status. |
| `GET` | `/workflows/{workflow_id}/trace` | Step-by-step execution trace. |
| `GET` | `/workflows/{workflow_id}/approval` | Full HITL review packet. |
| `POST` | `/approvals/{workflow_id}` | Record a reviewer's decision and resume. |
| `GET` | `/metrics` | Dashboard counters. |
| `GET` | `/health` | Component health. |

`POST /tickets` takes `{customer_id, subject, description}` — the field is
`subject`, not `title`. `POST /approvals/{id}` takes
`{approved, reviewer_name, comments}` and returns `409` if the workflow is not
awaiting approval.

The list, trace, approval-packet and metrics endpoints are additions beyond
SRS §36, which specifies only single-resource reads; the operations console
cannot function without them.

---

## Testing

```bash
pytest                                       # from the local venv
pytest --cov=app --cov-report=term-missing   # target >=80%
pytest tests/test_e2e.py -v                  # end-to-end pipeline
```

`pytest` runs from the venv, **not** inside the container — the image does not
ship `tests/`.

No Groq key or running infrastructure is required: the suite uses an in-memory
SQLite database, a fake Redis stream, a scripted chat model and a stubbed
retriever. `tests/test_e2e.py` drives the real API, queue, consumer, runner,
graph and MCP runtime end to end, substituting only those three external
services.

Frontend:

```bash
cd frontend
npm run build    # tsc -b && vite build
npm run lint
```

---

## Observability

Structured logs are always on; every node logs `workflow_id`, node name,
execution time, tool calls and retry count.

OpenTelemetry tracing (SRS §42) is **off by default** and adds spans for
FastAPI requests, LangGraph nodes and MCP tool calls:

```bash
OTEL_ENABLED=true docker compose up          # spans to container logs
OTEL_ENABLED=true OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318 docker compose up
```

Spans carry ids, durations, counts and status codes only — never customer data.

---

## Configuration

All settings come from `.env` (see `.env.example`). The ones that matter most:

| Variable | Default | Notes |
|----------|---------|-------|
| `GROQ_API_KEY` | – | Required for real workflow execution. |
| `HITL_REFUND_THRESHOLD` | `1000.0` | Refunds above this need human approval. |
| `HITL_CONFIDENCE_THRESHOLD` | `0.6` | Agent confidence below this routes to review. |
| `OTEL_ENABLED` | `false` | Enables tracing. |
| `RAG_SCORE_THRESHOLD` | `0.6` | Below this, retrieval reports insufficient information. |

If human approval fires more often than a demo wants, tune the HITL thresholds
rather than weakening the Risk Engine — the governance path working *is* the
feature.

---

## Known limitations

- **No authentication.** SRS §43 specifies JWT and RBAC; neither is
  implemented. Anyone who can reach the API or the dashboard can read every
  ticket and approve any paused workflow. Acceptable for local development
  only — this must be resolved before any shared deployment.
- **Single-tenant.** No tenant isolation in the schema or the queue.
- **Polling, not streaming.** The dashboard polls; there is no websocket or SSE
  channel.
