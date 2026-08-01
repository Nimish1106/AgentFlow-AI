# AgentFlow Operations Control Center

Internal operations and support console for AgentFlow AI (SRS §5, Phase 7).
Monitors ticket workflows, renders live execution traces, and provides the
human-in-the-loop approval interface.

This is **not** a customer-facing chat portal. Every user of this app is an
internal reviewer, operator or engineer.

## Stack

Vite 8 · React 19 · TypeScript 5.9 · TailwindCSS 4 · lucide-react

## Views

| View | What it shows |
|------|---------------|
| **Ticket & workflow operations hub** | Every ticket with its latest workflow state, customer tier, priority and status badges |
| **Live execution trace** | The SRS §37 pipeline as a timeline: per-node execution time, tool-call counts and LLM confidence |
| **HITL approval drawer** | Risk score and the Risk Engine's reasons, subscription and invoice context, agent judgements, and the approve/reject form |
| **Ticket ingestion simulator** | Submits a real ticket to trigger a backend workflow |

## Running it

Through Docker Compose (recommended — everything is wired up):

```bash
docker compose up --build       # from the repository root
```

The dashboard is then at <http://localhost:3000>.

Locally against a running backend:

```bash
npm install
npm run dev                     # http://localhost:5173
```

The Vite dev server proxies `/tickets`, `/workflows`, `/approvals`, `/metrics`
and `/health` to `http://localhost:8000`, so no CORS configuration or absolute
API URL is needed. Point it elsewhere with `VITE_DEV_API_TARGET`.

## Checks

```bash
npm run build      # tsc -b && vite build
npm run lint       # eslint
npm run typecheck  # tsc -b --noEmit
```

All three must be clean; the Docker build runs `npm run build`, so a type error
fails the image rather than shipping broken assets.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_API_BASE_URL` | *(empty)* | Absolute API URL. Leave unset — both the dev server and the production nginx proxy the API paths, so the browser sees one origin. |
| `VITE_POLL_INTERVAL_MS` | `4000` | Poll cadence for tickets and metrics. The execution trace polls at a fixed 2s. |
| `VITE_DEV_API_TARGET` | `http://localhost:8000` | Dev-server proxy target only. |

## Notes for future changes

- **Types are hand-maintained.** `src/api/types.ts` mirrors `app/api/schemas.py`;
  there is no code generation. Change both together.
- **Polling is the only data path** — the backend exposes no websocket or SSE.
  `usePolling` pauses while the tab is hidden, aborts in-flight requests on
  dependency change, and keeps the last good data on screen when a poll fails
  (blanking a populated table because one request failed is worse than showing
  slightly stale data with a warning).
- **Status colours live in `src/lib/status.ts`.** Add them there, not inline, so
  a badge, a table row and a timeline node cannot drift apart.
- **The pipeline definition is also in `status.ts`** (`PIPELINE`). It mirrors the
  graph topology in `app/graph/workflow.py`; if a node is added to the graph,
  add it here or the timeline will not show it.
- Every animation is wrapped in a `prefers-reduced-motion` guard — this console
  gets stared at for hours.
