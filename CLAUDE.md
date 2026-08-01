# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# AgentFlow AI

## Project

Enterprise Multi-Agent Customer Operations Platform

## Source of Truth

SRS.md is the single source of truth.

If implementation conflicts with SRS,
ask before making changes.

## Tech Stack

Python 3.11
FastAPI
LangGraph
PostgreSQL
Redis
Qdrant
SQLAlchemy
React
Vite
TailwindCSS
Docker Compose

## Development Rules

- Use async throughout
- Use type hints
- Use Pydantic v2
- Use SQLAlchemy 2.x
- Keep business logic out of FastAPI
- Agents never access databases directly
- Agents never make HTTP requests
- All external tools go through LangGraph ToolNode + Enterprise MCP Server
- Follow the folder structure from SRS
- Never implement future phases
- Complete one phase at a time

## Coding Standards

- Small modules
- SOLID
- Clean Architecture
- No duplicated code
- Production-ready code
- Add docstrings
- Add unit tests for new modules

## Before finishing any task

Always provide:
- Files created
- Files modified
- Commands to run
- Manual verification steps

## Repository status

**Phases 1-7 of 8 are complete** (SRS §48).

Phase 1 — project setup, PostgreSQL, Redis, FastAPI, Docker: `app/config` (Pydantic v2 settings), `app/database` (async SQLAlchemy 2.x session + async Redis), `app/models` (User, SupportTicket, Subscription, Invoice, WorkflowRun, AgentExecutionLog, AuditLog, enums), `app/services` (Ticket/Workflow/Queue + typed exceptions), `app/api/routes` (health, tickets, workflows), `app/observability/logging.py`, Alembic migration `0001_initial_schema`, `scripts/seed_database.py`, Docker Compose (postgres/redis/backend).

Phase 2 — LangGraph, GraphState, Supervisor, Task Planner: `app/graph/state.py` (GraphState/ExecutionTask/AgentResult + `build_initial_state`), `app/graph/constants.py` (Domain/AgentName), `app/graph/planner.py` (deterministic plan builder), `app/graph/llm.py` (Groq factory — the only place credentials are read), `app/graph/nodes/` (supervisor, planner), `app/graph/workflow.py` (`START -> supervisor -> task_planner -> END`), `app/prompts/supervisor.py`. The graph is **not yet wired into the API** — `POST /tickets` still only queues; the dispatcher that consumes the queue and runs the graph is a later phase.

Phase 3 — Enterprise MCP Server (`mcp` SDK 1.x, FastMCP over streamable-http): `app/mcp/server/main.py` (one server, `stateless_http=True`, run via `uvicorn app.mcp.server.main:app`, Compose service `enterprise-mcp`, port 8001 on the host), `app/mcp/server/tools/{billing,account,ticket,knowledge}.py` (12 namespaced tools per SRS §31), `app/mcp/server/runtime.py` (`run_tool`: session + `asyncio.timeout` + structured `ToolError` dicts + AuditLog row on every call, success or failure; `set_session_factory()` is the test seam), `app/mcp/schemas.py` (typed result models), `app/mcp/client.py` (`EnterpriseMCPClient` — consumed only by the Phase 4 ToolNode, not yet wired anywhere). New services: `billing_service.py` (deterministic `calculate_refund` — only `payment_status=duplicate` is auto-eligible), `account_service.py` (unlock is LOCKED→ACTIVE only), `knowledge_service.py` (Phase 5 stubs returning `insufficient_information`). Migration `0002_mcp_support`: `users.feature_flags` JSON, `ticket_notes` table, `audit_logs.workflow_id` nullable (MCP calls outside a workflow audit with NULL).

Phase 3 was verified end-to-end against the running Compose stack; two defects were found and fixed in the process:

- **MCP transport security.** FastMCP enables DNS-rebinding protection by default, which rejected every in-network request with `421 Misdirected Request` / "Invalid Host header" because the backend reaches the server as `http://enterprise-mcp:8000`. `create_mcp_server()` now passes `TransportSecuritySettings(allowed_hosts=..., allowed_origins=...)` listing `enterprise-mcp:8000`, `localhost:8000`, and `127.0.0.1:8000`. Any new hostname the server is reached by (a different Compose service name, an ingress host) must be added there or its calls will 421.
- **Seed ordering.** The models declare no ORM relationships, so SQLAlchemy's unit of work could not infer that `users` must be inserted before `subscriptions`/`invoices`, and `scripts/seed_database.py` failed with `invoices_user_id_fkey`. `seed()` now builds all companies, `add_all`s the users, `await session.flush()`es them, and only then adds the child rows. Keep this ordering in mind when seeding any future child table.

Phase 4 — the five agents + ToolNode (SRS §30, §31, §37): `app/graph/tools.py` (`_TOOL_SPECS` — 12 tool definitions with Pydantic arg schemas; `AGENT_TOOL_NAMES` — Billing gets billing_*, Account gets account_*, Technical gets only `knowledge_semantic_search` per SRS §30.5; `build_agent_tools()` bakes `workflow_id` into every tool coroutine so the LLM never sees it and MCP audit rows attribute calls; `call_mcp_tool_with_retry` — SRS §41: only structured `timeout` codes and transport exceptions retry, max 3 attempts, exponential backoff, exhaustion degrades to a structured `{"code": "unavailable"}` dict, never raises; `invalid_input`/`not_found` return to the LLM verbatim). `app/agents/base.py` (`run_agent_loop` — bind_tools → ToolNode over a **private message list** so parallel agents don't interleave in `GraphState.messages`, then `with_structured_output` for the closing summary; standalone ToolNode invocation on langgraph 1.2 requires `{"configurable": {"__pregel_runtime": Runtime(context=None)}}` in the config or it raises `Missing required config key`; `make_domain_agent_node` factory). `app/agents/{billing,account,technical}.py` (thin factories), `app/agents/policy.py` (LLM-only, no tools; `RISK_SCORES` low/medium/high → 0.2/0.5/0.9; verdict wins conflicts per SRS §40), `app/agents/response.py` (reads only GraphState/AgentResults; writes `final_response` — the Phase 6 Dispatcher node owns the terminal `workflow_status="completed"`), `app/agents/schemas.py` (AgentOutcome/PolicyOutcome/ResponseOutcome), `app/prompts/agents.py`. Graph topology in `app/graph/workflow.py`: supervisor → planner → plan-driven parallel fan-out to domain agents → policy (always) → response → END; `route_after_policy` sends a policy *evaluation failure* to END (no verdict → no customer reply) but a policy *rejection* (approved=False) still continues. Failure semantics: a domain-agent exception degrades to a failed AgentResult and the workflow continues (policy gates); Policy/Response failure sets `workflow_status="failed"`.

Parallel-safety (bit us during Phase 4): domain agents run in one superstep, so any key they write must carry a reducer or LangGraph raises `InvalidUpdateError`. `completed_agents` and `tool_history` are now `Annotated[List, operator.add]`; `shared_context` is `Annotated[Dict, merge_dicts]` — nodes return **only their own contribution** (agents namespace output under their agent name), never a spread of prior state, or values double-append. Domain agent nodes may write only: `agent_results`, `errors`, `completed_agents`, `tool_history`, `shared_context`, `messages`. `current_node` is unreduced — only nodes that run alone in a superstep (supervisor, planner, policy, response) may write it.

Phase 5 — RAG, Qdrant, knowledge ingestion (SRS §20, §32, §33): `app/rag/` — `chunking.py` (deterministic paragraph-aware `chunk_text`, sliding window with overlap for over-long paragraphs), `embeddings.py` (`FastEmbedModel` — fastembed/ONNX, lazy-loads on first `embed`, inference pushed to a worker thread; model name from `settings.embedding_model`, `BAAI/bge-small-en-v1.5`, 384 dims — ingestion and query must embed with the same model), `vector_store.py` (`KnowledgeVectorStore` over `AsyncQdrantClient`; **one** collection `knowledge`, doc kind is a `doc_type` payload field filtered with `MatchAny` — not separate collections; point ids are UUID5 of `source:chunk_index` so re-ingestion is an idempotent overwrite), `ingestion.py` (Markdown + minimal `--- title/doc_type ---` front matter → chunks → vectors → upsert), `retriever.py` (`KnowledgeRetriever` + cached `get_retriever()`), `schemas.py`. `KnowledgeService` now does real retrieval: `search_policy` filters doc_types `(refund_policy, sla, policy)`, `search_runbook` `(runbook, troubleshooting)`; zero hits (or all hits under `rag_score_threshold`, default 0.6 — bge cosine scores floor around 0.5 even for unrelated text, so a low threshold never triggers the guard; measured on the seed corpus relevant ≥0.7, nonsense ≤0.52) → the same `insufficient_information` payload as the Phase 3 stubs; retriever exceptions propagate so the MCP runtime audits them as failures — the service must never swallow errors into fake insufficient-info answers. Seed corpus in `docs/knowledge/*.md` (6 docs: refund_policy, sla, faq, product_doc, troubleshooting, runbook — a test asserts exactly this set); indexed **offline** via `docker compose exec backend python -m scripts.ingest_knowledge` (Dockerfile now `COPY docs ./docs`). Compose gained a `qdrant` service (v1.18.0 — keep the image minor version within 1 of the `qdrant-client` pin or the client warns on every connection; healthcheck via bash `/dev/tcp` because the image has no curl) and `QDRANT_URL` on backend + enterprise-mcp. The MCP knowledge tool contract did not change — agents still reach knowledge only through the MCP server, and the Technical agent still binds only `knowledge_semantic_search`. The Dockerfile pre-downloads the default model's weights at build time (`FASTEMBED_CACHE_PATH=/opt/fastembed_cache`) — without this the first knowledge call on a fresh container spends its entire 10s MCP timeout downloading weights and fails (observed live; the failure was audited and the retry policy would mask it, but cold start is guaranteed to time out). Overriding `EMBEDDING_MODEL` at runtime works but re-downloads on first embed. Audit note: `audit_logs.workflow_id` has an FK to `workflow_runs` in Postgres — a tool call with a fabricated workflow_id gets its audit row silently dropped (`_audit` logs and swallows insert failures by design); always smoke-test with a workflow_id created via `POST /tickets`.

Phase 6 — Results Aggregator, Risk Engine, HITL, workflow resume, queue dispatcher (SRS §37-§40, §14): the graph is finally **wired into the system**. New deterministic nodes (no LLM, no MCP): `app/graph/nodes/aggregator.py` (dedupes AgentResults keeping the *latest* per agent, splits success/failure, detects domain-vs-policy conflicts — policy wins per SRS §40 — and namespaces findings under agent names in `shared_context["aggregation"]`), `app/graph/nodes/risk_engine.py` (SRS §39 factors → `risk_level`/`risk_score`/`requires_hitl`/`reasons`; the *worst* factor sets the level; refund threshold is exclusive; a refund amount only counts when the same agent also reported eligibility, so a looked-up invoice isn't read as money leaving; **owns `risk_score`**, overriding the Policy Agent's raw value per SRS §28), `app/graph/nodes/hitl.py` (`interrupt()`; `parse_decision` accepts a bare bool or the §26 mapping and treats anything unparseable as *rejection* — an unreadable decision is never consent), `app/graph/nodes/dispatcher.py` (delivery only; owns the terminal `workflow_status="completed"`; a failed webhook logs into `errors` and still completes per SRS §13 step 14). Topology: `policy → results_aggregator → risk_engine → (human_approval if requires_hitl) → response → dispatcher → END`.

`app/graph/checkpointer.py` — `AsyncPostgresSaver` via `checkpointer_context()`; `to_psycopg_dsn` strips `+asyncpg`/`+psycopg` because the saver uses **psycopg v3**, not the app's asyncpg engine. It must be held open for the process lifetime (it owns a pool); `setup()` creates `checkpoints`/`checkpoint_blobs`/`checkpoint_writes`/`checkpoint_migrations` itself — those are **not** Alembic-managed.

`app/dispatcher/` — `runner.py` (`WorkflowRunner`: builds initial state from the ticket + subscription plan as `customer_tier`, invokes with `thread_id = workflow_id`, then persists the consequences the graph is forbidden to write — run status, one `agent_execution_logs` row per agent, `workflow_finished`/`hitl_requested`/`workflow_resumed`/`conflict_resolved` audit rows, and the ticket's `status`+`resolution`; an interrupt parks the run as `waiting_for_hitl`), `consumer.py` (Redis Streams consumer group, `mkstream=True` so it boots before the first ticket; **ACKs even failed jobs** — the outcome is already persisted, and an unacked poison job redelivers forever), `main.py` (`python -m app.dispatcher.main`, own Compose service, the only service holding `GROQ_API_KEY`). `POST /approvals/{workflow_id}` → `app/services/approval_service.py` audits the decision, flips the run to `running`, and enqueues a `resume` job — the endpoint **never runs the graph** (SRS §46); the status flip is flushed but committed only after the enqueue succeeds, so a Redis failure rolls back and leaves the run reviewable. Migration `0003_phase6_governance` adds `support_tickets.resolution` (SRS §36 requires it; §18.4 defines no column — deviation confirmed with the user).

Two defects found during live verification and fixed: **redis-py 8.x defaults `socket_timeout=5s`**, exactly the default `XREADGROUP` block window, so every idle poll raised `TimeoutError` and the loop logged a traceback — `build_redis_client()` now sets `socket_timeout = dispatcher_block_ms/1000 + 5s` headroom; keep that invariant if you change `DISPATCHER_BLOCK_MS`. And the Response Agent no longer sets `workflow_status="completed"` — the Dispatcher node does, since a drafted-but-undelivered response is not a completed workflow.

Live-run note: with the real Groq model, a routine 49 USD duplicate-charge refund still routed to HITL — the Policy Agent returned `approved=False` at confidence 0.50, which trips three Risk Engine factors at once (policy rejection, conflict with the billing agent, two sub-threshold confidences). The governance path is working as specified; if HITL fires more often than a demo wants, tune `HITL_CONFIDENCE_THRESHOLD` or the Policy prompt rather than weakening the Risk Engine.

Phase 7 — Enterprise Support Dashboard (SRS §5, §48): `frontend/` is a Vite 8 + React 19 + TypeScript 5.9 + TailwindCSS 4 SPA (`lucide-react` icons), served in Compose by `docker/Dockerfile.frontend` (multi-stage: `node:24-alpine` build → `nginx:1.29-alpine` runtime) on **host port 3000**. `docker/nginx.conf` serves the SPA *and* reverse-proxies `/tickets|/workflows|/approvals|/metrics|/health` to `backend:8000`, so the browser sees one origin — the upstream is a `set` variable, forcing per-request Docker DNS resolution, because a literal `proxy_pass` host makes nginx refuse to boot when the backend is not up yet. Views: `TicketsTable` (operations hub — status/tier/priority badges, status filter), `ExecutionTrace` (SRS §37 pipeline rendered as a timeline with per-node timings, tool-call counts and LLM confidence; stages with no trace row show as pending), `ApprovalDrawer` (HITL review packet + approve/reject form → `POST /approvals/{workflow_id}`), `TicketSimulator` (scenario presets → `POST /tickets`), `MetricsBar` (Active Workflows / Pending HITL Approvals / Avg Execution Time + three more). `usePolling` is the only data path (no websocket exists): it pauses while the tab is hidden, aborts in-flight requests on dep change, and **keeps the last good data on screen when a poll fails** rather than blanking a populated table. Tickets/metrics poll at 4s, the trace at 2s. Build is clean under `tsc -b` and `eslint` — note `react-hooks/refs` rejects assigning a ref during render, so `usePolling` syncs its fetcher ref inside an effect.

Phase 7 needed two **backend additions**, both agreed with the user before implementing:

- **Five read-only endpoints** (`app/api/routes/dashboard.py` + `app/services/dashboard_service.py`): `GET /tickets`, `GET /workflows`, `GET /workflows/{id}/trace`, `GET /workflows/{id}/approval`, `GET /metrics`. SRS §36 defines only single-resource reads, but §5 makes the React app a monitoring console, which cannot list anything through `GET /tickets/{id}`. These are pure projections — no writes, no LLM, no MCP; a test asserts the dashboard never builds the graph. They are registered **before** `tickets.router`/`workflows.router` in `app/main.py` because FastAPI matches in registration order and `/workflows/{workflow_id}` would otherwise try to parse `trace` as a UUID. Page size is capped at 200 (`MAX_LIMIT`). CORS is now enabled from `settings.cors_allow_origins` (comma-separated, never a wildcard per SRS §43).
- **Migration `0004_phase7_execution_trace`** adds `agent_execution_logs.confidence`/`summary`/`sequence` and `workflow_runs.risk_assessment` (JSON).

The trace itself comes from a new reduced GraphState channel, `node_executions` (`Annotated[List[NodeExecution], operator.add]`, built via `build_node_execution`). **Every** node appends one entry — including the deterministic governance nodes, which `AgentResult` cannot represent (it is a fixed SRS §23 contract that only reasoning agents produce, and it carries no timing). `confidence` is NULL for aggregator/risk_engine/dispatcher/human_approval: they do not reason, so they have no confidence to report. Because `node_executions` is reduced, adding it to a parallel domain agent's update was safe — `tests/test_agents.py` now derives the parallel-safe allowlist from GraphState's own reducer annotations instead of hardcoding it, so an unreduced key added to a parallel agent fails the test rather than surfacing as a runtime `InvalidUpdateError`.

Two governance rules were settled during Phase 7 and must not be regressed:

- **Risk data is never parsed from prose.** `workflow_runs.risk_assessment` holds `{score, level, requires_hitl, reasons}`, written by `WorkflowRunner` via `extract_risk_assessment()` (which maps the graph's `risk_level`/`risk_score` onto `level`/`score`) on **both** the completion and the HITL-pause paths — the reviewer's packet must be on the row before the run is advertised as awaiting approval. It returns None when the Risk Engine never ran, so "no assessment" stays distinguishable from "assessed as no risk". An earlier draft of `dashboard_service.py` reverse-engineered the score by string-splitting the Risk Engine's log summary (`score=0.90`); that was rejected — re-wording a log line would have silently blanked the risk shown to someone approving a refund. `_risk_field()` now reads the column.
- **`agent_execution_logs` is append-only.** An earlier draft did `DELETE`-then-reinsert to keep resumes idempotent; execution history is audit-adjacent (SRS §18.6) and is not rewritten. `_persist_trace` appends only the un-persisted tail and continues the existing `sequence`. The tail is found by `_resumed_prefix_length()`, which matches the longest **suffix** of the persisted node names against the **prefix** of the incoming trace. Matching by suffix (rather than counting rows) is what makes this correct when rows from an earlier attempt sit in front — a row count as the skip offset silently dropped a real node, which `test_history_is_never_deleted` caught. It returns 0 when nothing lines up, so the safe failure mode is a duplicate attempt in the history rather than a missing node.

Live-verified against the running stack: migration 0004 applied (`alembic current` → `0004 (head)`, all four columns confirmed in `psql`), all five endpoints return through both `:8000` and the nginx proxy on `:3000`, and a ticket submitted through the proxy executed end to end. A pre-0004 workflow correctly reports `risk_score: null` / `reasons: []` instead of a fabricated value.

Not started — Phase 8: testing, optimization, documentation.

`srs.md` is the authoritative contract. **Read it before writing any code** — specifically Section 16 (Architectural Constraints) and Section 46 (AI Coding Rules). When scaffolding new code, follow the folder layout in Section 47 rather than inventing one.

## What is being built

AgentFlow AI: a multi-agent customer-support workflow platform for B2B SaaS. A ticket is decomposed into a deterministic LangGraph workflow executed by specialised agents (Supervisor, Billing, Account, Technical, Policy, Response), with RAG for knowledge, MCP for all enterprise access, and human-in-the-loop approval for risky actions.

Target stack: Python 3.11+, FastAPI, LangGraph, Groq (LLM), PostgreSQL, Redis (queue + runtime memory), Qdrant (vectors), SQLAlchemy async, Pydantic v2, MCP Python SDK, React + Tailwind, OpenTelemetry, Docker Compose.

## Architecture invariants

These are non-negotiable and cut across many files — violating them is the main failure mode in this codebase.

**Reasoning is separate from execution.** LLMs decide; LangGraph controls flow; MCP performs I/O. An agent that "just queries Postgres directly" breaks the whole model.

**Agents never touch the outside world.** No SQL, no HTTP, no direct env-var reads, no agent-to-agent calls. An agent binds tools via `.bind_tools()` and emits a `tool_call`. A LangGraph `ToolNode` intercepts it, calls the Enterprise MCP client, and returns a `tool_message`. Only the ToolNode talks to MCP. Tool names are namespaced (`billing_get_invoice`, `knowledge_semantic_search`).

**GraphState is the single source of truth.** Nodes return a state-update dict (`return {"agent_results": [result]}`) — never mutate state in place. Fields written by parallel agents must carry a reducer so concurrent branches append/merge instead of clobbering (`agent_results`, `errors`, `completed_agents`, `tool_history` use `operator.add`; `shared_context` uses `merge_dicts`). Every node checkpoints; every workflow is resumable from its checkpoint.

**Everything async.** `async def` throughout, `httpx` not `requests`, SQLAlchemy async / asyncpg, async LangGraph and Redis clients.

**No business logic in FastAPI routes.** `POST /tickets` validates, creates the workflow row, queues it, and returns `202 Accepted` immediately — the graph runs via `BackgroundTasks`. FastAPI must never call an LLM or MCP.

**Task Planner is plain deterministic Python** — no LLM, no MCP. It turns Supervisor output into an ordered `ExecutionTask` list.

**Response Agent reads only GraphState/AgentResults** — no MCP, no DB.

**RAG grounding.** Retrieve before generating. If no relevant context is found, say "insufficient information" rather than filling the gap.

## Key contracts

Every agent returns the same `AgentResult` shape (`agent_name`, `status`, `confidence`, `summary`, `actions_taken`, `tool_calls`, `output_data`) so the Results Aggregator can merge outputs uniformly. Full definitions of `GraphState`, `ExecutionTask`, and `AgentResult` are in Section 21.

HITL uses `workflow_id` as the LangGraph `thread_id` in the `RunnableConfig`. `POST /approvals/{workflow_id}` records the decision and enqueues a `resume` job; the **dispatcher** resumes that thread with `Command(resume={"approved", "reviewer_name", "comments"})` — approval interrupts a workflow, it never restarts one, and the API never runs the graph itself.

Pydantic models need `model_config = ConfigDict(from_attributes=True)` to parse SQLAlchemy ORM objects.

Storage ownership does not overlap: PostgreSQL = persistent business data + checkpoints + audit logs; Redis = queue and *ephemeral* workflow memory only (never permanent customer records); Qdrant = knowledge base.

## Failure handling

Retry only recoverable failures (MCP timeout, DB connection, vector-search timeout) — max 3 attempts, exponential backoff, log every retry. Do not retry invalid input or a missing customer; stop the workflow, write the audit log, return failure. Conflicting agent recommendations resolve in favour of the Policy Agent, with the conflict recorded in audit logs. A failed webhook dispatch logs and continues — resolution is already complete by then, so it must not crash the workflow.

## Commands

```bash
docker compose up --build                              # postgres, redis, qdrant, backend, enterprise-mcp, dispatcher, frontend (migrations run on boot)
docker compose exec backend python -m scripts.seed_database
docker compose exec backend python -m scripts.ingest_knowledge   # index docs/knowledge into Qdrant (offline, idempotent)
pytest                                                 # target >=80% coverage; run from the local venv
alembic upgrade head                                   # local venv only
docker compose logs -f dispatcher                      # watch a workflow execute node by node

cd frontend && npm install                             # once
npm run dev                                            # Vite dev server on :5173, proxies the API to :8000
npm run build                                          # tsc -b && vite build - must be clean
npm run lint                                           # eslint - must be clean
```

The dashboard is at **http://localhost:3000** once the stack is up. Changing backend code requires `docker compose up -d --build --force-recreate backend enterprise-mcp dispatcher` — a plain `up -d --build` leaves already-running containers on their old image, which shows up as new endpoints 404ing and `alembic current` failing to locate a revision that exists on disk.

Note that `pytest` runs from the local venv, not inside the backend container — the container image does not ship the `tests/` directory, so `docker compose exec backend pytest` collects nothing.

Services share a custom Docker bridge network. The backend reaches MCP at `http://enterprise-mcp:8000` (host port 8001) and Qdrant at `http://qdrant:6333` (host port 6333). The frontend container reaches the API at `http://backend:8000` through its own nginx proxy (host port 3000 → container 80).

The `dispatcher` service is the only place a workflow actually runs, and the only service that needs `GROQ_API_KEY` — if a ticket sits at `pending` forever, check that container first. Its logs are the execution trace: one line per node with `workflow_id`, timings and decisions.

To smoke-test MCP against the running stack:

```bash
docker compose exec -T backend python -c "import asyncio; from app.mcp.client import EnterpriseMCPClient; print(asyncio.run(EnterpriseMCPClient('http://enterprise-mcp:8000').list_tools()))"
docker compose exec -T postgres psql -U agentflow -d agentflow -c "select performed_by, workflow_id, action from audit_logs;"
```

`audit_logs`' time column is named `timestamp`, not `created_at`.

The dashboard's read endpoints are **unauthenticated**. SRS §43 lists JWT authentication and RBAC, and neither is implemented anywhere in the system yet — the API has no auth layer at all, which was true before Phase 7 as well. Anyone who can reach port 3000 or 8000 can read every ticket and customer record and approve any paused workflow. This is acceptable only for local development; it must be resolved before any shared or public deployment, and is the largest outstanding gap against the SRS.
