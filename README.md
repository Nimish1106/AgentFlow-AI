# AgentOps AI

Enterprise Multi-Agent Customer Operations Platform for B2B SaaS.
`srs.md` is the authoritative specification.

**Status: Phase 1 complete** (project setup, PostgreSQL, Redis, FastAPI, Docker).
Later phases (LangGraph, MCP, agents, RAG, HITL, frontend) are not implemented yet.

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
```
