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

**Phases 1-4 of 8 are complete** (SRS §48).

Phase 1 — project setup, PostgreSQL, Redis, FastAPI, Docker: `app/config` (Pydantic v2 settings), `app/database` (async SQLAlchemy 2.x session + async Redis), `app/models` (User, SupportTicket, Subscription, Invoice, WorkflowRun, AgentExecutionLog, AuditLog, enums), `app/services` (Ticket/Workflow/Queue + typed exceptions), `app/api/routes` (health, tickets, workflows), `app/observability/logging.py`, Alembic migration `0001_initial_schema`, `scripts/seed_database.py`, Docker Compose (postgres/redis/backend).

Phase 2 — LangGraph, GraphState, Supervisor, Task Planner: `app/graph/state.py` (GraphState/ExecutionTask/AgentResult + `build_initial_state`), `app/graph/constants.py` (Domain/AgentName), `app/graph/planner.py` (deterministic plan builder), `app/graph/llm.py` (Groq factory — the only place credentials are read), `app/graph/nodes/` (supervisor, planner), `app/graph/workflow.py` (`START -> supervisor -> task_planner -> END`), `app/prompts/supervisor.py`. The graph is **not yet wired into the API** — `POST /tickets` still only queues; the dispatcher that consumes the queue and runs the graph is a later phase.

Phase 3 — Enterprise MCP Server (`mcp` SDK 1.x, FastMCP over streamable-http): `app/mcp/server/main.py` (one server, `stateless_http=True`, run via `uvicorn app.mcp.server.main:app`, Compose service `enterprise-mcp`, port 8001 on the host), `app/mcp/server/tools/{billing,account,ticket,knowledge}.py` (12 namespaced tools per SRS §31), `app/mcp/server/runtime.py` (`run_tool`: session + `asyncio.timeout` + structured `ToolError` dicts + AuditLog row on every call, success or failure; `set_session_factory()` is the test seam), `app/mcp/schemas.py` (typed result models), `app/mcp/client.py` (`EnterpriseMCPClient` — consumed only by the Phase 4 ToolNode, not yet wired anywhere). New services: `billing_service.py` (deterministic `calculate_refund` — only `payment_status=duplicate` is auto-eligible), `account_service.py` (unlock is LOCKED→ACTIVE only), `knowledge_service.py` (Phase 5 stubs returning `insufficient_information`). Migration `0002_mcp_support`: `users.feature_flags` JSON, `ticket_notes` table, `audit_logs.workflow_id` nullable (MCP calls outside a workflow audit with NULL).

Phase 3 was verified end-to-end against the running Compose stack; two defects were found and fixed in the process:

- **MCP transport security.** FastMCP enables DNS-rebinding protection by default, which rejected every in-network request with `421 Misdirected Request` / "Invalid Host header" because the backend reaches the server as `http://enterprise-mcp:8000`. `create_mcp_server()` now passes `TransportSecuritySettings(allowed_hosts=..., allowed_origins=...)` listing `enterprise-mcp:8000`, `localhost:8000`, and `127.0.0.1:8000`. Any new hostname the server is reached by (a different Compose service name, an ingress host) must be added there or its calls will 421.
- **Seed ordering.** The models declare no ORM relationships, so SQLAlchemy's unit of work could not infer that `users` must be inserted before `subscriptions`/`invoices`, and `scripts/seed_database.py` failed with `invoices_user_id_fkey`. `seed()` now builds all companies, `add_all`s the users, `await session.flush()`es them, and only then adds the child rows. Keep this ordering in mind when seeding any future child table.

Phase 4 — the five agents + ToolNode (SRS §30, §31, §37): `app/graph/tools.py` (`_TOOL_SPECS` — 12 tool definitions with Pydantic arg schemas; `AGENT_TOOL_NAMES` — Billing gets billing_*, Account gets account_*, Technical gets only `knowledge_semantic_search` per SRS §30.5; `build_agent_tools()` bakes `workflow_id` into every tool coroutine so the LLM never sees it and MCP audit rows attribute calls; `call_mcp_tool_with_retry` — SRS §41: only structured `timeout` codes and transport exceptions retry, max 3 attempts, exponential backoff, exhaustion degrades to a structured `{"code": "unavailable"}` dict, never raises; `invalid_input`/`not_found` return to the LLM verbatim). `app/agents/base.py` (`run_agent_loop` — bind_tools → ToolNode over a **private message list** so parallel agents don't interleave in `GraphState.messages`, then `with_structured_output` for the closing summary; standalone ToolNode invocation on langgraph 1.2 requires `{"configurable": {"__pregel_runtime": Runtime(context=None)}}` in the config or it raises `Missing required config key`; `make_domain_agent_node` factory). `app/agents/{billing,account,technical}.py` (thin factories), `app/agents/policy.py` (LLM-only, no tools; `RISK_SCORES` low/medium/high → 0.2/0.5/0.9; verdict wins conflicts per SRS §40), `app/agents/response.py` (reads only GraphState/AgentResults; writes `final_response` + `workflow_status="completed"`), `app/agents/schemas.py` (AgentOutcome/PolicyOutcome/ResponseOutcome), `app/prompts/agents.py`. Graph topology in `app/graph/workflow.py`: supervisor → planner → plan-driven parallel fan-out to domain agents → policy (always) → response → END; `route_after_policy` sends a policy *evaluation failure* to END (no verdict → no customer reply) but a policy *rejection* (approved=False) still reaches Response. Failure semantics: a domain-agent exception degrades to a failed AgentResult and the workflow continues (policy gates); Policy/Response failure sets `workflow_status="failed"`.

Parallel-safety (bit us during Phase 4): domain agents run in one superstep, so any key they write must carry a reducer or LangGraph raises `InvalidUpdateError`. `completed_agents` and `tool_history` are now `Annotated[List, operator.add]`; `shared_context` is `Annotated[Dict, merge_dicts]` — nodes return **only their own contribution** (agents namespace output under their agent name), never a spread of prior state, or values double-append. Domain agent nodes may write only: `agent_results`, `errors`, `completed_agents`, `tool_history`, `shared_context`, `messages`. `current_node` is unreduced — only nodes that run alone in a superstep (supervisor, planner, policy, response) may write it.

Not started — Phases 5-8: RAG/Qdrant (knowledge tools still return `insufficient_information`; Qdrant not yet in `requirements.txt` or Compose), Results Aggregator + Risk Engine + HITL interrupt + workflow resume (Postgres-backed checkpointer — today the graph compiles with `InMemorySaver`), the dispatcher that consumes the Redis queue and runs the graph (`POST /tickets` still only queues; the graph is **not wired into the API**), React frontend. The packages `app/rag` and `app/dispatcher` hold only empty `__init__.py` files; `frontend/` and `docs/` are empty.

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

HITL uses `workflow_id` as the LangGraph `thread_id` in the `RunnableConfig`. `POST /approvals/{workflow_id}` loads state by that thread and resumes with `Command(resume=True)` — approval interrupts a workflow, it never restarts one.

Pydantic models need `model_config = ConfigDict(from_attributes=True)` to parse SQLAlchemy ORM objects.

Storage ownership does not overlap: PostgreSQL = persistent business data + checkpoints + audit logs; Redis = queue and *ephemeral* workflow memory only (never permanent customer records); Qdrant = knowledge base.

## Failure handling

Retry only recoverable failures (MCP timeout, DB connection, vector-search timeout) — max 3 attempts, exponential backoff, log every retry. Do not retry invalid input or a missing customer; stop the workflow, write the audit log, return failure. Conflicting agent recommendations resolve in favour of the Policy Agent, with the conflict recorded in audit logs. A failed webhook dispatch logs and continues — resolution is already complete by then, so it must not crash the workflow.

## Commands

```bash
docker compose up --build                              # postgres, redis, backend, enterprise-mcp (migrations run on boot)
docker compose exec backend python -m scripts.seed_database
pytest                                                 # target >=80% coverage; run from the local venv
alembic upgrade head                                   # local venv only
```

Note that `pytest` runs from the local venv, not inside the backend container — the container image does not ship the `tests/` directory, so `docker compose exec backend pytest` collects nothing.

Services share a custom Docker bridge network. The backend reaches MCP at `http://enterprise-mcp:8000` (host port 8001). Later phases add qdrant and frontend to Compose.

To smoke-test MCP against the running stack:

```bash
docker compose exec -T backend python -c "import asyncio; from app.mcp.client import EnterpriseMCPClient; print(asyncio.run(EnterpriseMCPClient('http://enterprise-mcp:8000').list_tools()))"
docker compose exec -T postgres psql -U agentflow -d agentflow -c "select performed_by, workflow_id, action from audit_logs;"
```

`audit_logs`' time column is named `timestamp`, not `created_at`.
