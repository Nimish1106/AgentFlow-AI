# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# AgentOps AI

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

**Phases 1-2 of 8 are complete** (SRS §48).

Phase 1 — project setup, PostgreSQL, Redis, FastAPI, Docker: `app/config` (Pydantic v2 settings), `app/database` (async SQLAlchemy 2.x session + async Redis), `app/models` (User, SupportTicket, Subscription, Invoice, WorkflowRun, AgentExecutionLog, AuditLog, enums), `app/services` (Ticket/Workflow/Queue + typed exceptions), `app/api/routes` (health, tickets, workflows), `app/observability/logging.py`, Alembic migration `0001_initial_schema`, `scripts/seed_database.py`, Docker Compose (postgres/redis/backend).

Phase 2 — LangGraph, GraphState, Supervisor, Task Planner: `app/graph/state.py` (GraphState/ExecutionTask/AgentResult + `build_initial_state`), `app/graph/constants.py` (Domain/AgentName), `app/graph/planner.py` (deterministic plan builder), `app/graph/llm.py` (Groq factory — the only place credentials are read), `app/graph/nodes/` (supervisor, planner), `app/graph/workflow.py` (`START -> supervisor -> task_planner -> END`), `app/prompts/supervisor.py`. The graph is **not yet wired into the API** — `POST /tickets` still only queues; the dispatcher that consumes the queue and runs the graph is a later phase.

Not started — Phases 3-8: Enterprise MCP server and tools, the six agents, RAG/Qdrant, Results Aggregator + Risk Engine + HITL, React frontend. The packages `app/agents`, `app/mcp`, `app/rag`, `app/dispatcher` hold only empty `__init__.py` files; `frontend/` and `docs/` are empty. Qdrant and the MCP SDK are not yet in `requirements.txt`. Checkpointing uses an in-memory saver; the Postgres-backed checkpointer arrives with workflow resume in Phase 6.

`srs.md` is the authoritative contract. **Read it before writing any code** — specifically Section 16 (Architectural Constraints) and Section 46 (AI Coding Rules). When scaffolding new code, follow the folder layout in Section 47 rather than inventing one.

## What is being built

AgentOps AI: a multi-agent customer-support workflow platform for B2B SaaS. A ticket is decomposed into a deterministic LangGraph workflow executed by specialised agents (Supervisor, Billing, Account, Technical, Policy, Response), with RAG for knowledge, MCP for all enterprise access, and human-in-the-loop approval for risky actions.

Target stack: Python 3.11+, FastAPI, LangGraph, Groq (LLM), PostgreSQL, Redis (queue + runtime memory), Qdrant (vectors), SQLAlchemy async, Pydantic v2, MCP Python SDK, React + Tailwind, OpenTelemetry, Docker Compose.

## Architecture invariants

These are non-negotiable and cut across many files — violating them is the main failure mode in this codebase.

**Reasoning is separate from execution.** LLMs decide; LangGraph controls flow; MCP performs I/O. An agent that "just queries Postgres directly" breaks the whole model.

**Agents never touch the outside world.** No SQL, no HTTP, no direct env-var reads, no agent-to-agent calls. An agent binds tools via `.bind_tools()` and emits a `tool_call`. A LangGraph `ToolNode` intercepts it, calls the Enterprise MCP client, and returns a `tool_message`. Only the ToolNode talks to MCP. Tool names are namespaced (`billing_get_invoice`, `knowledge_semantic_search`).

**GraphState is the single source of truth.** Nodes return a state-update dict (`return {"agent_results": [result]}`) — never mutate state in place. Fields written by parallel agents must use `Annotated[List[...], operator.add]` so concurrent branches append instead of clobbering (`agent_results` and `errors` both need this). Every node checkpoints; every workflow is resumable from its checkpoint.

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
docker compose up --build                              # postgres, redis, backend (migrations run on boot)
docker compose exec backend python -m scripts.seed_database
pytest                                                 # target >=80% coverage
alembic upgrade head                                   # local venv only
```

Services share a custom Docker bridge network. Later phases add qdrant, enterprise-mcp, and frontend to Compose; the backend will reach MCP at an internal hostname (e.g. `http://enterprise-mcp:8000`).
