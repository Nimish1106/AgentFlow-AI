# AgentOps AI

Enterprise Multi-Agent Customer Operations Platform for B2B SaaS.
`srs.md` is the authoritative specification.

**Status: Phases 1-2 complete.**

- Phase 1 — project setup, PostgreSQL, Redis, FastAPI, Docker.
- Phase 2 — LangGraph state, deterministic Task Planner, Supervisor Agent, base workflow graph.

Later phases (MCP, the domain agents, RAG, HITL, frontend) are not implemented yet.
The graph is not yet wired into `POST /tickets` — that arrives with the queue dispatcher.

## Configuration

Copy `.env.example` to `.env`. Set `GROQ_API_KEY` before running the workflow
graph — the Supervisor Agent raises `LLMNotConfiguredError` without it. The API,
database and queue all run fine without a key.

## Quickstart (Docker)

```bash
cp .env.example .env
docker compose up --build
```

Backend: http://localhost:8000 (docs at /docs). Migrations run automatically.

Seed mock data:

```bash
docker compose exec backend python -m scripts.seed_database
```

## Quickstart (local venv)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate on Unix)
pip install -r requirements.txt
cp .env.example .env             # point DATABASE_URL/REDIS_URL at local services
docker compose up -d postgres redis
alembic upgrade head
python -m scripts.seed_database
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
pytest --cov=app --cov-report=term-missing   # target >=80%
```

Tests need no Groq key — the Supervisor is exercised against a fake chat model.
