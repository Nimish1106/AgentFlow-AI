# AgentFlow AI — Interview Knowledge Base

A study document for defending, modifying, debugging and extending this system under
questioning. Written to explain **why**, not what. Every number in it was measured
against the running system, not estimated.

**Verified system facts (as of writing):** 86 Python modules, 27 test files,
400 tests passing, 92% coverage, 4 Alembic migrations, 12 MCP tools, 7 Docker
services, 10 graph nodes.

---

## 1. Project Overview & The Business Problem

### The problem in one paragraph

B2B SaaS support teams drown in tickets that are individually simple but collectively
expensive: "I was charged twice", "my dashboard is locked", "does my plan cover X".
Each requires looking up billing records, checking policy, deciding an action, and
writing a reply. A human does this in 5–15 minutes. An LLM could draft it in seconds
— but you cannot let an LLM issue refunds unsupervised, and you cannot explain to an
auditor why a model decided to move money.

**AgentFlow AI resolves support tickets autonomously where it safely can, and escalates
to a human where it cannot — with a complete audit trail either way.**

### Why this framing matters in an interview

The interesting engineering problem here is **not** "call an LLM". It's:

> How do you build a system where an LLM makes decisions, but the *system* — not the
> model — controls what actually happens, and every action is explainable after the fact?

That constraint drives nearly every architectural decision in this codebase. If you
remember one thing, remember this: **reasoning is separated from execution**. LLMs
decide; LangGraph controls flow; MCP performs I/O. Nothing else touches the outside
world.

### What the system actually does, end to end

1. A ticket arrives (`POST /tickets`) and is queued. The API returns `202` immediately.
2. A separate dispatcher process picks the job off a Redis stream.
3. A Supervisor agent classifies intent and domains.
4. A **deterministic** planner turns that classification into an ordered task list.
5. Domain agents (Billing / Account / Technical) run **in parallel**, using tools.
6. A Policy agent evaluates compliance — always, on every ticket.
7. A deterministic Results Aggregator merges findings and detects conflicts.
8. A deterministic Risk Engine scores risk and decides if a human is needed.
9. If risk is high, the workflow **pauses mid-execution** and waits for a reviewer.
10. A Response agent drafts the customer reply.
11. A Dispatcher node delivers it and marks the workflow complete.

Steps 4, 7, 8 and 11 contain **no LLM and no I/O**. That's deliberate and is the
single most defensible design choice in the project (see §7.3).

---

## 2. Why This Project Was Chosen

Answer this honestly in interviews — a rehearsed "it's innovative" reads as hollow.

**It exercises the genuinely hard parts of agentic systems**, not the easy parts.
A chatbot demo proves you can call an API. This project forced solutions to:

- **Non-deterministic components inside a deterministic system.** The LLM is
  unreliable; the workflow must not be.
- **Long-running, resumable work.** A workflow can pause for hours awaiting human
  approval, survive a process restart, and resume exactly where it stopped. That
  requires real checkpointing, not in-memory state.
- **Parallel state merging.** Three agents writing to shared state concurrently is a
  distributed-systems problem in miniature (see §7.4 — it produced a real bug).
- **Auditability of machine decisions.** Every tool call and every governance decision
  writes a row. This is what makes the system deployable in a regulated context.
- **A boundary an LLM cannot cross.** Agents have no database driver and no HTTP
  client. Not "shouldn't" — *don't*.

**What it deliberately is not:** a RAG chatbot, a prompt-chaining demo, or an
"AutoGPT"-style open-ended agent loop. Open-ended agent autonomy is exactly what you
cannot ship when actions have financial consequences.

---

## 3. Architecture & Request Flow

### 3.1 The seven services

| Service | Role | Why it's separate |
|---|---|---|
| `postgres` | Business data, checkpoints, audit logs | — |
| `redis` | Job queue (Streams) + ephemeral memory | — |
| `qdrant` | Knowledge vectors | — |
| `backend` | FastAPI HTTP API | Must stay fast; never runs a workflow |
| `dispatcher` | Executes workflows | A workflow takes ~20s; that cannot block HTTP |
| `enterprise-mcp` | The only path to enterprise data | Enforces the agent boundary at the network level |
| `frontend` | React dashboard + nginx proxy | — |

**The most important structural decision: `backend` and `dispatcher` are separate
processes.** The API validates, persists, queues, and returns `202 Accepted` in
milliseconds. The dispatcher owns the graph, the LLM client, the MCP client and the
checkpointer. `GROQ_API_KEY` exists **only** in the dispatcher.

Why this matters: if the graph ran inside FastAPI via `BackgroundTasks`, a 20-second
workflow would occupy a worker, an API restart would kill in-flight workflows, and you
could not scale reasoning capacity independently of request capacity. Splitting them
also makes the security story simple — the internet-facing service holds no LLM
credentials.

### 3.2 The full request flow

```
Browser (:3000)
   │  nginx serves the SPA and reverse-proxies /tickets|/workflows|/approvals|/metrics
   ▼
POST /tickets ──► FastAPI route (validate only)
                     │
                     ├─► TicketService: INSERT support_tickets, INSERT workflow_runs (pending)
                     ├─► QueueService: XADD to Redis stream  ◄── commit ONLY after enqueue
                     └─► 202 Accepted {workflow_id}
                                    │
        ┌───────────────────────────┘  (HTTP request is over)
        ▼
dispatcher: WorkflowConsumer.XREADGROUP  (consumer group, blocking)
        │
        ▼
WorkflowRunner.run(workflow_id)
        │  builds GraphState from ticket + subscription tier
        │  config = {"configurable": {"thread_id": str(workflow_id)}}
        ▼
compiled LangGraph (checkpoint written after EVERY node)
        │
   supervisor ──► task_planner ──► ┌ billing_agent  ┐
   (LLM)          (pure Python)    │ account_agent  │ parallel, plan-driven
                                   └ technical_agent┘   each: bind_tools → ToolNode → MCP
                                          │
                       policy_agent ◄──────┘   (LLM, no tools; verdict wins conflicts)
                            │
                    results_aggregator      (pure Python)
                            │
                       risk_engine          (pure Python; OWNS risk_score)
                            │
              ┌─────────────┴──────────────┐
        requires_hitl                   otherwise
              │                            │
     human_approval ──► interrupt()        │
        (raises GraphInterrupt out of ainvoke;
         run parked as waiting_for_hitl)   │
              │                            │
              │  POST /approvals/{id}      │
              │    → audit the decision    │
              │    → flip run to running   │
              │    → XADD resume job       │
              │  (the API NEVER runs graph)│
              │                            │
              └──► dispatcher resumes with Command(resume={...})
                   interrupt() RETURNS the decision this time
                            │
                    response_agent          (LLM; reads only GraphState)
                            │
                       dispatcher           (delivery; owns workflow_status="completed")
                            │
                           END
        │
        ▼
WorkflowRunner persists what the graph is forbidden to write:
   • workflow_runs.status / current_node / completed_at / risk_assessment
   • agent_execution_logs (one row per node, append-only)
   • audit_logs (workflow_finished / hitl_requested / workflow_resumed / conflict_resolved)
   • support_tickets.status + .resolution
```

**The single most-asked question about this diagram:** *why does the graph not write to
the database itself?* Because a node that writes to Postgres is a node that cannot be
replayed. Checkpoint-resume re-executes node bodies (the HITL node body runs twice per
approval — once to pause, once to record). If nodes performed writes, every resume
would duplicate them. Nodes return state; the runner — which knows whether this was a
fresh run or a resume — performs the writes exactly once.

---

## 4. Tech Stack: Every Choice and Its Alternatives

### LangGraph over LangChain agents / CrewAI / AutoGen / hand-rolled

| Option | Why rejected |
|---|---|
| LangChain `AgentExecutor` | A `while` loop around an LLM. No checkpointing, no parallel fan-out, no mid-execution pause. Cannot resume after a restart. |
| CrewAI | Agents delegate to each other conversationally. Control flow lives *inside* the prompts, so it isn't inspectable or testable. Exactly what a governance system must not do. |
| AutoGen | Conversation-first, open-ended. Strong for research, wrong where the number of steps must be bounded and known. |
| Hand-rolled state machine | I'd have written checkpointing, interrupt/resume and parallel state reduction myself. That's a year of work LangGraph already does correctly. |

**The deciding feature was `interrupt()`.** HITL is the core requirement: a workflow must
stop mid-execution, persist, survive a process restart, and resume with a human's
decision injected at the exact point it stopped. LangGraph does this natively via
checkpointing plus `Command(resume=...)`. Nothing else on the list does.

**Trade-off accepted:** LangGraph's API moves fast (1.x had breaking changes), and
standalone `ToolNode` invocation required an undocumented config key
(`{"configurable": {"__pregel_runtime": Runtime(context=None)}}`) or it raised
`Missing required config key`. I pay that cost for correct checkpointing.

### MCP over direct function tools

This is the choice most interviewers probe, because it looks like unnecessary
indirection. The honest answer:

**What it buys:** the agent boundary becomes a *network* boundary, not a code
convention. An agent physically cannot query Postgres — it has no driver and no
connection string. It emits a `tool_call`; a ToolNode calls an HTTP service. Every call
crosses a process where auditing, timeouts and error normalisation are enforced in one
place (`run_tool` in `app/mcp/server/runtime.py`), for all 12 tools, unavoidably.

**What it costs:** a network hop (~5–15ms locally), a service to operate, and
DNS-rebinding configuration (see §7.1).

**The honest framing:** for a single-team project, in-process tools would be simpler and
I'd concede that. MCP earns its cost when tools are shared across teams or when you must
*prove* to an auditor that the reasoning layer had no data access. That's the actual
argument — not "MCP is a standard".

### Groq over OpenAI / Anthropic / local

Latency. The measured trace shows the supervisor at 4.5s and the billing agent at
11.9s; on a slower provider that same workflow crosses a minute and the demo stops
feeling like software. Groq's LPU inference is dramatically faster per token at
comparable quality for classification and summarisation, which is all these agents do.
The LLM is constructed in exactly one place (`app/graph/llm.py`), so swapping providers
is a one-file change.

### Postgres for checkpoints (not Redis)

Redis is the queue and *ephemeral* memory. Checkpoints are the opposite of ephemeral:
they're how a workflow parked for a human survives a deploy. Storage ownership never
overlaps — Postgres = durable business data + checkpoints + audit; Redis = transient;
Qdrant = knowledge.

**Sharp implementation detail worth knowing:** `AsyncPostgresSaver` uses **psycopg v3**,
not the app's asyncpg driver, so `to_psycopg_dsn()` strips `+asyncpg` from the URL. Its
four tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
`checkpoint_migrations`) are created by the saver's own `setup()` and are **not
Alembic-managed** — the library owns that schema version.

### Redis Streams over Celery / RabbitMQ / LISTEN-NOTIFY

Streams give consumer groups (horizontal scaling), acknowledgements, and redelivery of
unacked messages after a crash — which is exactly "every failure must be recoverable".
Celery adds a broker plus a result backend plus a worker model for machinery I don't
need. Redis was already in the stack for ephemeral memory.

### fastembed / ONNX over OpenAI embeddings

Embeddings run locally: no per-query cost, no network in the retrieval path, no customer
text leaving the process. `BAAI/bge-small-en-v1.5`, 384 dimensions.

**Non-obvious operational cost:** the model weights must be baked into the Docker image
(`FASTEMBED_CACHE_PATH=/opt/fastembed_cache`, pre-downloaded at build time). Without
that, the first knowledge call on a fresh container spends its entire 10s MCP timeout
downloading weights and fails. I hit this live.

---

## 5. Database Design

### 5.1 Tables and ownership

| Table | Purpose | Notable columns |
|---|---|---|
| `users` | Enterprise customers | `account_status` enum, `feature_flags` JSON |
| `subscriptions` | Plan + price + renewal | `plan` enum drives `customer_tier` |
| `invoices` | Billing history | `payment_status` enum — `duplicate` is the refund trigger |
| `support_tickets` | The ticket | `resolution` (added in 0003) |
| `workflow_runs` | One graph execution | `risk_assessment` JSON (added in 0004) |
| `agent_execution_logs` | Per-node execution trace | `confidence`, `summary`, `sequence` (0004) |
| `audit_logs` | Immutable business-action record | `workflow_id` nullable, `timestamp` |
| `ticket_notes` | Internal notes (0002) | — |

Plus four LangGraph checkpoint tables the saver manages itself.

### 5.2 Design decisions worth defending

**UUID primary keys everywhere.** Ids are generated by the application before insert,
which lets `POST /tickets` return a `workflow_id` in the same transaction that creates
it, and avoids leaking volume through sequential ids.

**`audit_logs.workflow_id` is nullable.** MCP tools can be invoked outside a workflow
(smoke tests, admin use). Forcing the FK would either block those calls or invent a fake
workflow. **Sharp edge:** the FK to `workflow_runs` means a tool call with a *fabricated*
workflow_id gets its audit row silently dropped — `_audit` logs and swallows insert
failures deliberately, because auditing must never break the tool result. Always
smoke-test with a real workflow_id.

**`agent_execution_logs.sequence` exists because timestamps cannot order these rows.**
Parallel domain agents finish inside the same superstep and Postgres' `now()` is
transaction-scoped, so they share `created_at` exactly. Without an explicit ordinal the
trace renders in random order. (The same fact bit the test suite — see §11.2.)

**`workflow_runs.risk_assessment` is JSON, and this was a corrected mistake.** My first
draft of the dashboard reverse-engineered the risk score by string-splitting the Risk
Engine's *log summary* (`score=0.90`). That means re-wording a log line silently blanks
the risk shown to someone approving a refund. It was replaced with a real column written
from the graph's own output. **Governance data is never parsed from prose.** If asked for
one example of a design mistake I caught and fixed, use this one.

**No ORM relationships declared.** The models have FKs but no `relationship()`. That
means SQLAlchemy's unit of work cannot infer insert order, which broke seeding
(`invoices_user_id_fkey`) until `seed()` was changed to flush users before children. The
trade-off: explicit joins everywhere, no accidental lazy-load N+1 in an async context —
where a lazy load raises rather than silently blocking.

### 5.3 Migration history as a narrative

- `0001` — initial schema.
- `0002` — MCP support: `feature_flags`, `ticket_notes`, nullable audit FK.
- `0003` — `support_tickets.resolution`. **SRS §36 requires the API to return a
  resolution but §18.4 defines no column.** I raised the conflict rather than inventing
  a column silently, and got agreement first.
- `0004` — trace columns + `risk_assessment`.

---

## 6. The LangGraph Workflow

### 6.1 GraphState and reducers — the part that produces real bugs

```python
class GraphState(TypedDict):
    workflow_id: str; ticket_id: str; customer_id: str
    issue_text: str; customer_tier: str; ticket_priority: str
    execution_plan: List[ExecutionTask]

    # Reduced channels: parallel branches append/merge instead of clobbering
    completed_agents: Annotated[List[str], operator.add]
    shared_context:   Annotated[Dict, merge_dicts]
    messages:         Annotated[List[BaseMessage], add_messages]
    tool_history:     Annotated[List[str], operator.add]
    agent_results:    Annotated[List[AgentResult], operator.add]
    errors:           Annotated[List[str], operator.add]
    node_executions:  Annotated[List[NodeExecution], operator.add]

    # Unreduced: only nodes that run ALONE in a superstep may write these
    current_node: str
    risk_score: float
    requires_hitl: bool
    approval_status: Optional[str]
    workflow_status: str
    retry_count: int
    final_response: Optional[str]
```

**The rule that matters:** three domain agents execute in one superstep. Any key two of
them might write **must** carry a reducer, or LangGraph raises `InvalidUpdateError`.
`current_node` has no reducer — so a parallel agent writing it crashes the workflow.

**Two corollaries that are easy to get wrong:**

1. Nodes return **only their own contribution**, never a spread of prior state. Returning
   `{**state["shared_context"], "mine": x}` through a merge reducer double-appends.
2. Agents namespace their output under their own agent name in `shared_context`, so
   concurrent merges cannot collide on a key.

**How this is enforced in tests, and why that's the good version:**
`tests/test_agents.py` derives the parallel-safe allowlist from GraphState's *own reducer
annotations* via `typing.get_type_hints(..., include_extras=True)`. A hardcoded list
would drift. Now, adding an unreduced key to a parallel agent fails a unit test instead
of surfacing as a runtime `InvalidUpdateError` in production.

### 6.2 Routing

| Router | Decision | Rationale |
|---|---|---|
| `route_after_supervisor` | failed → END | No intent means the planner would plan against a guess. |
| `route_after_planner` | fan out to planned domain agents; none → policy | Plan-driven, not hardcoded. Policy+Response alone is a valid workflow. |
| `route_after_policy` | failed → END, else aggregator | **A policy *rejection* continues** (the customer is told it's under review); only a policy *evaluation failure* ends the run — no verdict must never mean a customer reply. |
| `route_after_risk` | `requires_hitl` → human_approval, else response | — |
| `route_after_response` | failed → END, else dispatcher | Nothing to deliver. |

That distinction between "policy said no" and "policy failed to answer" is a favourite
interview probe. Rejection is a *decision* and flows on; failure is an *absence of
decision* and stops.

### 6.3 Failure semantics per node

- **Domain agent raises** → degrades to a failed `AgentResult`, workflow continues. The
  Policy agent sees the failure and decides whether resolution is still safe. Partial
  information is better than no answer, *if* something gates it.
- **Policy or Response raises** → `workflow_status="failed"`, workflow stops. These are
  the gate and the customer-facing output; neither can be skipped.
- **Dispatcher webhook fails** → logged into `errors`, workflow still completes. The
  resolution is already persisted; delivery failure must not undo it.

### 6.4 Why the Task Planner has no LLM

`app/graph/planner.py` is pure Python: Supervisor output → ordered `ExecutionTask` list.
Identical input produces byte-identical plans. That's what makes a workflow reproducible
from a checkpoint. If an LLM built the plan, a resumed workflow could take a different
path than the one that was checkpointed, and the audit trail would describe a run that
never happened.

Same reasoning for the Aggregator, Risk Engine and Dispatcher: **an LLM in the
governance path makes approvals unauditable.** Given identical state, the Risk Engine
must always reach the same decision. The measured trace confirms these nodes cost
0–1ms — determinism is also free.

---

## 7. Agents: Responsibilities and Boundaries

| Agent | LLM | Tools | Writes | Why it exists |
|---|---|---|---|---|
| Supervisor | Yes | None | intent, domains, priority | Turns prose into structure so the planner can be deterministic |
| Task Planner | **No** | None | `execution_plan` | Reproducibility (§6.4) |
| Billing | Yes | `billing_*` (3) | AgentResult | Invoice/refund domain |
| Account | Yes | `account_*` (3) | AgentResult | Lockouts, feature flags |
| Technical | Yes | `knowledge_semantic_search` **only** | AgentResult | Diagnosis is a knowledge problem, not a mutation problem |
| Policy | Yes | **None** | verdict, risk | Judges others' results; must not gather its own evidence |
| Aggregator | **No** | None | `shared_context["aggregation"]` | Merge + conflict detection |
| Risk Engine | **No** | None | `risk_score`, `requires_hitl` | Governance decision |
| HITL | **No** | None | `approval_status` | `interrupt()` boundary |
| Response | Yes | **None** | `final_response` | Drafts the reply from state only |
| Dispatcher | **No** | None | `workflow_status="completed"` | Delivery |

**Three boundaries interviewers push on:**

*Why does Technical get only one tool?* It diagnoses; it does not mutate. Giving it
account tools would let a diagnosis silently change account state. Least privilege at the
tool-binding level.

*Why does Policy have no tools?* It evaluates what others found. If it could gather its
own evidence it could contradict the agents it's meant to judge using data they never
saw, and conflict resolution becomes incoherent.

*Why does Response have no DB access?* It writes what the customer reads. If it could
query, it could tell a customer something no agent verified and no policy approved. It
reads GraphState and nothing else.

**`workflow_id` is injected, never exposed to the LLM.** `build_agent_tools()` bakes it
into every tool coroutine via closure. The model never sees it, cannot hallucinate it,
and every MCP audit row is correctly attributed.

**One more subtlety in `run_agent_loop`:** each agent runs its ToolNode over a **private
message list**, and only its closing summary is written back to `GraphState.messages`.
Without that, three parallel agents interleave their tool-call chatter into one shared
channel and each agent sees the others' half-finished reasoning.

---

## 8. MCP Architecture

**One server, four namespaces, twelve tools:**

```
billing_get_invoice        account_get_customer         ticket_get_ticket
billing_get_subscription   account_unlock_dashboard     ticket_update_ticket
billing_calculate_refund   account_update_feature_flag  ticket_add_internal_note
knowledge_semantic_search  knowledge_search_policy      knowledge_search_runbook
```

### 8.1 `run_tool` — the choke point

Every tool goes through one function, which gives, unavoidably, for all twelve:

1. A DB session scoped to the call
2. `asyncio.timeout(mcp_tool_timeout_seconds)` — SRS §16.8
3. Exception → structured `ToolError` translation. **Exceptions never cross the MCP
   boundary**; the LLM receives `{"error": ..., "code": ...}` and can reason about it
4. An `AuditLog` row on **every** call, success *and* failure
5. An OTel span with the outcome code

You cannot add a tool that forgets to audit. That's the entire argument for centralising
it here rather than in each tool.

### 8.2 Retry policy (SRS §41) — precision matters

```
timeout / transport error  → retry, max 3, exponential backoff
invalid_input / not_found  → return to the LLM verbatim, NO retry
retries exhausted          → {"code": "unavailable"}, never raise
```

Retrying `not_found` is pointless — the record won't materialise. Retrying
`invalid_input` is worse: it re-sends bad arguments and the LLM never learns to correct
them. Returning the error verbatim lets the model fix its own call. And exhaustion
degrades to a structured dict rather than raising, so one flaky tool cannot take down a
workflow that could still resolve on partial information.

### 8.3 Business logic lives in services, not tools

`calculate_refund` is deterministic Python in `billing_service.py`: only
`payment_status=duplicate` is auto-eligible; `refunded` / `pending` / `paid` each return
a structured rejection with a reason. The LLM decides *whether to ask*; the service
decides *what's true*. Refund eligibility is a business rule, not an inference.

Likewise `unlock_dashboard` is LOCKED→ACTIVE only. A suspended account is a deliberate
state and an agent must not undo it.

---

## 9. RAG Pipeline

```
docs/knowledge/*.md  (6 docs: refund_policy, sla, faq, product_doc,
                      troubleshooting, runbook)
   │  front matter: --- title / doc_type ---
   ▼
chunk_text()      paragraph-aware, sliding window w/ overlap for long paragraphs
   ▼
FastEmbedModel    BAAI/bge-small-en-v1.5, 384-dim, ONNX, in a worker thread
   ▼
Qdrant            ONE collection "knowledge"; doc kind is a payload field
                  filtered with MatchAny — not separate collections
                  point id = UUID5(source:chunk_index) → re-ingestion is an
                  idempotent overwrite, never a duplicate
   ▼
KnowledgeRetriever → KnowledgeService → MCP knowledge tools → Technical agent
```

### Decisions worth defending

**One collection, not three.** `search_policy` and `search_runbook` are payload filters
(`MatchAny` on `doc_type`), not separate collections. Separate collections would mean
maintaining three schemas and would make cross-cutting search impossible. Adding a doc
type is a payload value, not a migration.

**UUID5 point ids.** Deterministic from `source:chunk_index`, so re-running ingestion
overwrites in place. A random id would duplicate the corpus on every run.

**Ingestion is offline and idempotent.** `python -m scripts.ingest_knowledge`, run
explicitly. Indexing on boot would make container start time depend on corpus size and
re-embed unchanged documents every deploy.

**The score threshold is measured, not guessed.** `rag_score_threshold = 0.6`. bge cosine
scores *floor around 0.5 even for unrelated text* — so a naive low threshold (0.2) never
fires and the "insufficient information" guard silently never triggers. Measured on the
seed corpus: relevant hits ≥0.7, nonsense ≤0.52. 0.6 sits in the gap. **If asked one
question about RAG tuning, this is the answer to give** — it shows the threshold was
derived from the embedding model's actual behaviour rather than copied from a tutorial.

**The service must never fake insufficient-information.** Zero hits (or all hits below
threshold) → the structured `insufficient_information` payload. But retriever
*exceptions* propagate, so the MCP runtime audits them as failures. A Qdrant outage must
look like an outage, not like "we have no policy on refunds" — that distinction is the
difference between a visible incident and a silently wrong customer answer.

---

## 10. Governance: Risk Engine & HITL

### 10.1 Risk factors (SRS §39)

| Factor | Effect |
|---|---|
| Refund above `HITL_REFUND_THRESHOLD` | high + HITL |
| Sensitive op (suspension, permission/flag change) | high + HITL |
| Policy rejection (`approved=False`) | high + HITL |
| Domain-vs-policy conflict | medium |
| Any agent failed (incomplete picture) | medium + HITL |
| Confidence below `HITL_CONFIDENCE_THRESHOLD` | medium + HITL |

**The worst factor sets the level.** High always forces HITL.

**A subtle correctness detail:** a refund amount only counts when *the same agent* also
reported eligibility. Otherwise an invoice merely *looked up* reads as money leaving the
business, and every billing enquiry escalates. That check is the difference between a
usable system and one that routes everything to a human.

**The Risk Engine owns `risk_score`**, overriding the Policy Agent's raw value (SRS §28
data ownership). One component owns each piece of data.

### 10.2 HITL mechanics

`interrupt()` raises `GraphInterrupt` out of `ainvoke` **after** the checkpoint is
written. The runner catches it, parks the run as `waiting_for_hitl`, and persists the
risk packet **before** the run is advertised as awaiting approval — a reviewer must never
open a review with no assessment on the row.

On resume, `Command(resume=decision)` makes `interrupt()` **return** rather than raise,
so the HITL node body executes twice per approval. That's why nodes must not perform
side effects.

**`parse_decision` treats anything unparseable as rejection.** A malformed decision
payload is not consent. Fail closed on the money-moving path.

### 10.3 A live-run finding worth quoting

A routine **49 USD** duplicate-charge refund still routed to HITL. Why: the Policy Agent
returned `approved=False` at confidence 0.50, which trips three factors simultaneously —
policy rejection, conflict with the billing agent, and two sub-threshold confidences.

The governance path worked exactly as specified. The *tuning* is aggressive. The correct
response is to tune `HITL_CONFIDENCE_THRESHOLD` or the Policy prompt — **not** to weaken
the Risk Engine. Saying this in an interview shows you can distinguish "the system is
broken" from "the policy is conservative".

---

## 11. Challenges, Bugs and How They Were Solved

This is the highest-value section for interviews. Each entry is a real defect found by
running the system, with the reasoning that fixed it.

### 11.1 MCP calls returned `421 Misdirected Request`

**Symptom:** every in-network MCP call failed with "Invalid Host header".
**Cause:** FastMCP enables DNS-rebinding protection by default and the backend reaches
the server as `http://enterprise-mcp:8000` — a hostname not in the default allowlist.
**Fix:** `TransportSecuritySettings(allowed_hosts=..., allowed_origins=...)` listing
`enterprise-mcp:8000`, `localhost:8000`, `127.0.0.1:8000`.
**Lasting rule:** any new hostname the server is reached by must be added there, or its
calls 421. A defence-in-depth default that looks like a bug until you know why it exists.

### 11.2 Two ordering bugs caused by transaction-scoped `now()`

**Bug A — parallel agents share a timestamp.** Postgres' `now()` is transaction-scoped
and SQLite's `CURRENT_TIMESTAMP` has one-second resolution. Rows written in quick
succession share a value, and `id` is a random UUID4, so `ORDER BY timestamp, id` is
effectively random. Fixed with an explicit `sequence` ordinal.

**Bug B — a test that passed alone and failed in the suite.** `ORDER BY timestamp, id`
over audit rows passed in isolation; in the full run the suite got *faster*, all five
rows landed in the same second, and ordering went random. The fix was better than a
tiebreak: `load_audit_events` returns rows unordered, and the test asserts sequence
through the workflow's **observable state at each step**. That's a stronger assertion —
it proves the reviewer's decision is durable *before* the resume job is consumed.

**Lesson:** a test that depends on wall-clock resolution is a flaky test wearing a
disguise. Assert on causality, not on timestamps.

### 11.3 Redis `TimeoutError` on every idle poll

**Symptom:** the dispatcher logged a traceback every 5 seconds while completely idle.
**Cause:** redis-py 8.x defaults `socket_timeout=5s`, which is *exactly* the default
`XREADGROUP` block window. The socket read deadline expired at the same instant the
blocking read legitimately returned empty.
**Fix:** `socket_timeout = dispatcher_block_ms/1000 + 5s` headroom, with a test
(`test_socket_timeout_outlives_the_blocking_read`) that encodes the invariant so changing
`DISPATCHER_BLOCK_MS` can't silently reintroduce it.
**Lesson:** when two independent timeouts are equal, they race. The outer deadline must
always outlive the inner one.

### 11.4 Row fan-out: one ticket returned twice

**Symptom:** `GET /tickets` returned a ticket twice while `total` still said 1.
**Cause:** the subscription-tier join was a plain outer join, so a customer with two
subscriptions (an upgrade history — completely normal) duplicated their ticket. The
latest-workflow join had the same defect, and subtler: it matched on `MAX(started_at)`,
and two runs created in one transaction share `now()` exactly, so a *retried* ticket
duplicated.
**Fix:** both became correlated scalar subqueries (`_tier_subquery`,
`_latest_workflow_subquery`) with a deterministic tiebreak, so a ticket is always exactly
one row. `TestNoRowFanOut` covers both shapes plus page overflow.
**Lesson:** joining to a to-many relationship to fetch one attribute is a fan-out waiting
for realistic data. Test with two children, never one.

### 11.5 `agent_execution_logs` — DELETE-then-reinsert was wrong

My first draft deleted and re-inserted all trace rows on every persist, to make resumes
idempotent. **Execution history is audit-adjacent (SRS §18.6) and is not rewritten.**

The replacement appends only the un-persisted tail, via `_resumed_prefix_length()`, which
matches the longest **suffix** of persisted node names against the **prefix** of the
incoming trace. Matching by suffix rather than counting rows is what makes it correct
when rows from an earlier attempt sit in front — using a row count as the skip offset
silently dropped a real node, which `test_history_is_never_deleted` caught. It returns 0
when nothing lines up, so the safe failure mode is a *duplicate* attempt in history
rather than a *missing* node.

**Lesson:** when a safe failure mode exists, engineer toward it deliberately.

### 11.6 `GraphInterrupt` was making every approval look like a fault

OTel's span `__exit__` sets ERROR status when handed *any* exception. Since HITL pauses by
raising `GraphInterrupt`, every human approval appeared as an error in the trace.
**Fix:** `span()` checks for `GraphBubbleUp` and closes the span cleanly. A pause is
control flow, not a failure (SRS §38).

### 11.7 Cold-start embedding timeout

First knowledge call on a fresh container consumed its whole 10s MCP timeout downloading
model weights. Fixed by pre-downloading at image build time. Retry policy would have
*masked* this — but cold start is guaranteed, not intermittent, so masking it would mean
every fresh deploy fails its first knowledge query.

### 11.8 A reporting error I made and corrected

I told the user a live workflow "completed with `risk_score=0.2`, no HITL". The API showed
`waiting_for_hitl`; the logs showed `risk_level=high risk_score=0.90 requires_hitl=True`
with four reasons. I had read the trace wrong and retracted it explicitly.

Worth including because interviews probe how you handle being wrong: **the governance
path worked; my reading of it didn't.** Verify against the system, not against your
expectation of it.

---

## 12. Design Patterns & SOLID

### Patterns actually used (not a textbook list)

| Pattern | Where | Why |
|---|---|---|
| **Factory** | `make_domain_agent_node`, `build_agent_tools`, `create_mcp_server` | Three agents differ only in tools + prompt; a factory removes three near-identical files |
| **Repository/Service** | `app/services/*` | Business logic out of routes and out of nodes; the same service backs both an MCP tool and an HTTP route |
| **Strategy** | Router functions | Routing is a pluggable, unit-testable pure function of state |
| **Decorator** | `traced_node` | Adds tracing without touching node bodies |
| **Context manager** | `checkpointer_context`, `run_tool` | Guarantees pool/session cleanup on every path |
| **Dependency injection** | FastAPI `Depends`, `set_session_factory()` | Real seams for tests, not monkeypatching |
| **Reducer** | GraphState annotations | Concurrent merge without locks |
| **Envelope** | Queue jobs `{kind, workflow_id, ticket_id, decision}` | One stream, ordered per workflow, two job kinds |

### SOLID, concretely

**Single responsibility** — the sharpest example is the split between the graph
(decides), the runner (persists) and the API (accepts). Also visible in
`workflow_status="completed"`: the Response Agent used to set it; it was moved to the
Dispatcher because *a drafted-but-undelivered response is not a completed workflow*.

**Open/closed** — adding a tool means a spec entry plus a service method; `run_tool`,
auditing, timeout and retry are untouched. Adding a node means one `add()` call, and it's
traced automatically because instrumentation happens at graph-assembly time.

**Liskov** — every agent returns the same `AgentResult` shape, so the Aggregator merges
them without knowing which agent produced what.

**Interface segregation** — `AGENT_TOOL_NAMES` gives each agent only its own tools.
Technical gets exactly one.

**Dependency inversion** — nodes depend on the `GraphState` contract, not on Postgres.
`WorkflowRunner` takes a `session_factory`, so tests inject SQLite. The MCP runtime's
`set_session_factory()` is an explicit test seam.

---

## 13. API Design

### Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/tickets` | **202**, body uses `subject` (not `title`) |
| GET | `/tickets` | List — Phase 7 addition, capped at 200 |
| GET | `/tickets/{id}` | Detail incl. `resolution` |
| GET | `/workflows` | List, filterable by status |
| GET | `/workflows/{id}` | Status + current node |
| GET | `/workflows/{id}/trace` | Per-node timings, tool counts, confidence |
| GET | `/workflows/{id}/approval` | Reviewer packet |
| POST | `/approvals/{id}` | 200 / 404 / **409** / 422 |
| GET | `/metrics` | Dashboard aggregates |
| GET | `/health` | — |

### Decisions

**`202 Accepted`, not `200`.** The work hasn't happened yet. `202` plus a `workflow_id`
is the honest answer, and it's what allows the API to stay millisecond-fast.

**`409` for a workflow not awaiting approval.** Not `400` (the request is well-formed) and
not `404` (the workflow exists). It's a state conflict, and it makes double-approval
safely idempotent-ish: the second reviewer gets a clear "already decided".

**Registration order is load-bearing.** `dashboard.router` registers **before**
`workflows.router`, because FastAPI matches in order and `/workflows/{workflow_id}` would
otherwise try to parse `trace` as a UUID and 422. A comment in `app/main.py` says so.

**The list endpoints are a documented SRS deviation.** §36 defines only single-resource
reads, but §5 makes the React app a monitoring console — which cannot list anything
through `GET /tickets/{id}`. I raised it, got agreement, and documented it rather than
quietly adding routes.

**A test asserts the dashboard never builds the graph.** It monkeypatches
`build_workflow_graph` to raise. That's how SRS §46 ("FastAPI never calls an LLM or MCP")
is enforced mechanically instead of by convention.

---

## 14. Frontend Architecture

Vite 8 + React 19 + TypeScript 5.9 + TailwindCSS 4 + `lucide-react`, served by nginx.

### Structure

```
frontend/src/
  api/client.ts        typed fetch wrapper + ApiError
  api/types.ts         response types mirroring the Pydantic schemas
  hooks/usePolling.ts  the ONLY data path
  lib/format.ts        durations, relative time, money, ids
  lib/status.ts        status → semantic mapping (single source of truth)
  components/
    Shell.tsx          nav rail + top bar
    primitives.tsx     Status, Pill, Panel, Th, Button, Field, Empty, Skeleton…
    OverviewView.tsx   metrics + recent activity
    TicketsView.tsx    operations hub (dense table)
    WorkflowsView.tsx  run list + trace side by side
    ApprovalsView.tsx  review queue + decision pane
    ExecutionTrace.tsx timeline with timings/tools/confidence
    TicketComposer.tsx scenario-preset modal
```

### Decisions

**Polling, not WebSockets.** No WebSocket exists on the backend, and adding one means
connection state, reconnection, and a message protocol for data that changes every few
seconds. Polling at 4s (lists) / 2s (trace) is sufficient and cannot desynchronise.
`usePolling` pauses while the tab is hidden, aborts in-flight requests on dependency
change, and — the important part — **keeps the last good data on screen when a poll
fails** rather than blanking a populated table. A transient 500 shouldn't erase an
operator's work.

**Status semantics centralised in `lib/status.ts`.** Every status→colour decision resolves
through one map. Without it, "running" is blue in four places and drifts in the fifth.

**Approvals is a route, not a drawer.** It was originally a drawer opened from a table
badge. A queue people are accountable for clearing deserves its own destination.
Risk assessment and the money at issue sit directly above the decision controls, so
nothing that matters is below the fold at the moment of clicking Approve. Approve and
Reject carry equal visual weight and **neither is autofocused** — releasing a refund
should require aim, not reflex.

**nginx same-origin proxy.** It serves the SPA *and* proxies the API paths to
`backend:8000`, so the browser sees one origin and CORS is a non-issue in production.
**Sharp detail:** the upstream is a `set` variable, forcing per-request Docker DNS
resolution — with a literal `proxy_pass` host, nginx refuses to *boot* if the backend
isn't up yet, which makes container start order load-bearing.

### The light-theme redesign (a design-systems question)

Converting dark→light is not an inversion. Three things genuinely reverse:

1. **Elevation.** On dark, surfaces come forward by getting lighter. On light, the canvas
   is soft gray (`#f6f7f9`), panels are pure white, and inset regions go *deeper* gray.
2. **Interaction.** Hover/active states darken here, lighten there.
3. **Status hues split in two.** A hue legible as text on white is too dark to read as a
   5px dot; a hue vivid enough for a dot fails contrast as text. Every semantic carries a
   text-safe value **and** a `-solid` graphic value. Amber shows it best: `#8a5a00` as
   text (5.9:1) vs `#c27803` as a dot.

**Contrast was measured, not asserted** — and the measurement caught my own error. I'd
commented `fg-faint` as "~4.5:1"; it was actually **4.10:1 on white, 3.82:1 on the
canvas**, failing AA for timestamps and hints. Darkened to `#6a7280` (4.85 / 4.52). It
still measures 4.28 on inset surfaces, which is acceptable *only* because its two uses
there are disabled-control text (WCAG 1.4.3 exempts inactive controls) and input
placeholders on white fields. That constraint is written into the token file rather than
rounded away.

---

## 15. Testing Strategy

**400 tests, 92% coverage, 27 files.** Coverage target was ≥80%.

### The layers

**Unit tests** for deterministic logic — planner, aggregator, risk engine, `parse_decision`,
`to_psycopg_dsn`, chunking, retry classification. These are pure functions; they're cheap
and they pin down governance behaviour exactly.

**Service tests** against **aiosqlite**, so the suite needs no running Postgres. Trade-off
accepted knowingly: SQLite differs on JSON operators and timestamp resolution — which is
precisely how bug 11.2B surfaced. Postgres-specific behaviour (row fan-out, `now()`
semantics) was verified live.

**E2E tests** (`tests/test_e2e.py`, 21 tests) drive the whole pipeline as one system:
`POST /tickets` → Redis stream → consumer → runner → graph → HITL interrupt →
`POST /approvals/{id}` → resume → response → dispatcher → persisted resolution.

*Real* in E2E: the FastAPI app, both services, the queue envelope, the consumer including
consumer-group and ACK semantics, the runner, every node and edge, the checkpointer, and
the MCP runtime with its audit writes.

*Substituted*, because a unit suite cannot require them: Groq (`ScriptedLLM`, keyed by
output schema), Qdrant (`RecordingRetriever`), Redis (`FakeRedisStream`).

**`FakeRedisStream` implements XADD/XREADGROUP/XACK plus consumer groups and a pending
set.** The pending set is not gold-plating — without pending tracking, the ACK policy
("ACK even failed jobs") cannot be asserted at all.

### What the tests honestly cannot prove

They prove the **system wiring**. They cannot prove the Groq model behaves well — no
offline test can. Say this plainly; claiming otherwise is the fastest way to lose
credibility.

### Two test-design points worth repeating

**Assert on causality, not timestamps** (§11.2).

**Derive invariants from the code, don't restate them.** `tests/test_agents.py` reads
GraphState's reducer annotations to compute the parallel-safe allowlist. A hardcoded list
would drift out of sync with the state definition it's supposed to guard.

---

## 16. Observability

**Three tiers, one trace:** FastAPI (auto-instrumented) → LangGraph nodes → MCP tool
calls, each with the right `service.name`.

**Off by default (`OTEL_ENABLED=false`).** The unit suite, the local venv and any offline
run must work with no collector listening. An observability layer that fails closed when
its collector is down is worse than none. With tracing on and no endpoint, spans go to the
console exporter so the tree is visible in `docker compose logs`.

**Three invariants, each with a test:**
1. **Never crash the caller.** A broken tracer degrades to an untraced block.
2. **Never suppress a real exception.**
3. **Never record customer data** (SRS §43). Attributes are ids, durations, counts and
   status codes. `test_node_spans_carry_ids_and_metrics_only` asserts a customer name and
   an invoice amount *cannot* reach a span.

**Instrumentation at graph-assembly time, not per node.** `traced_node` wraps every
`add_node` through a local `add()` helper, so a new node cannot be registered untraced by
accident. Span attributes come from the node's own `node_executions` entry, so the timing
on a span and the timing in `agent_execution_logs` are literally the same measurement —
they can never disagree.

---

## 17. Performance — Measured, Not Assumed

Live trace of a real duplicate-charge workflow:

| Node | Time | Notes |
|---|---|---|
| supervisor | 4548ms | LLM |
| task_planner | 1ms | pure Python |
| billing_agent | 11920ms | LLM + **5 tool calls** |
| policy_agent | 672ms | LLM |
| results_aggregator | 0ms | pure Python |
| risk_engine | 0ms | pure Python |
| response_agent | 2285ms | LLM |
| dispatcher | 0ms | pure Python |

**Conclusion: ~99% of wall-clock is Groq inference.** The deterministic governance nodes
are already free. Optimising Python here would be optimising 1ms out of 19,000.

**The one visible structural inefficiency:** the billing agent makes five tool calls for
one invoice question (`agent_max_tool_rounds` is 8). That is prompt/tool-loop *behaviour*,
not a code path. Reducing it means tightening the Billing prompt or the tool descriptions
and re-measuring — a behavioural change with a correctness risk. **I left it alone rather
than guessing**, and what Phase 8 added is the instrumentation to see it at all.

This is a deliberately strong interview answer: *the win here was making the cost visible,
and declining to "optimise" something I couldn't measure the consequences of.*

### Performance work that IS in place

- Parallel domain agents (fan-out, not sequential)
- `202` + queue, so HTTP never waits on inference
- Local embeddings (no network in retrieval)
- Correlated scalar subqueries instead of fan-out joins
- Page size capped at 200
- Connection pooling (SQLAlchemy async engine + psycopg pool for checkpoints)
- Model weights baked into the image

---

## 18. Security

### What's implemented

- **Secrets only from env.** `GROQ_API_KEY` exists in exactly one service. `app/graph/llm.py`
  is the only module that reads LLM credentials.
- **Parameterised SQL everywhere** via SQLAlchemy. No string-built queries.
- **Input validation** at the boundary with Pydantic v2.
- **Internal exceptions never leak.** MCP returns structured error codes; routes map
  typed service exceptions to status codes.
- **No customer data in traces or logs** (§16), enforced by test.
- **CORS from an explicit allowlist**, never a wildcard.
- **Least privilege at tool level** — Technical binds one read-only tool.
- **Fail-closed governance** — unparseable approval = rejection.
- **MCP transport security** — explicit host allowlist (§11.1).

### The honest gap — state it before you're asked

**There is no authentication or authorisation anywhere in the system.** SRS §43 lists JWT
and RBAC; neither exists. Anyone who can reach port 3000 or 8000 can read every ticket and
customer record **and approve any paused workflow**.

This is acceptable for local development only and is the largest outstanding gap against
the SRS. Volunteering it demonstrates you know where the boundary of "done" is. The
follow-up ("how would you add it?") is answered in §21.

Note the risk is worse than a normal missing-auth gap: the approvals endpoint is a
*money-moving* action with an unauthenticated `reviewer_name` string. Audit rows record
`reviewer:<name>` with nothing verifying it.

---

## 19. Scalability

**What scales horizontally today:** the dispatcher. Redis consumer groups mean N
dispatchers share one stream with no coordination — each job goes to exactly one consumer,
and an unacked job from a crashed worker is redelivered. Add replicas and reasoning
throughput scales linearly. The backend is stateless and scales behind a load balancer.

**Ordering guarantee:** one stream keeps per-workflow ordering, so a `resume` cannot
overtake its `start`.

**What would break first, in order:**

1. **Groq rate limits.** ~99% of latency is inference, so the LLM provider is the ceiling,
   not the code. Needs request-level rate limiting and a queue depth signal.
2. **Postgres connection count.** Every dispatcher holds an app pool *and* a psycopg
   checkpoint pool. At tens of workers, add PgBouncer.
3. **`agent_execution_logs` and `audit_logs` growth.** Append-only and never pruned. Needs
   time-based partitioning and an archival policy.
4. **Checkpoint table growth.** LangGraph writes a checkpoint per node per workflow —
   roughly 10 rows per ticket. Needs retention for completed workflows.
5. **Single Qdrant instance.** Fine for six documents; needs clustering for a real corpus.

**What's deliberately single-instance:** the MCP server is stateless
(`stateless_http=True`), so it scales trivially — it just hasn't needed to.

---

## 20. Deployment

```bash
docker compose up --build          # 7 services; backend runs `alembic upgrade head` on boot
docker compose exec backend python -m scripts.seed_database
docker compose exec backend python -m scripts.ingest_knowledge
```

**Boot order is explicit:** postgres/redis/qdrant healthchecked → backend (migrations) →
enterprise-mcp + dispatcher wait for backend to have started → frontend.

**Migrations run in the backend's start command**, so a fresh volume self-provisions. In a
real deployment this becomes a separate migration job — a scaled backend would run
`upgrade head` N times concurrently.

**Three operational traps I hit, all worth mentioning:**

1. `docker compose up -d --build` leaves **already-running** containers on their old
   image. Symptom: new endpoints 404, `alembic current` can't find a revision that exists
   on disk. Fix: `--force-recreate backend enterprise-mcp dispatcher`.
2. `pytest` runs from the local venv, **not** in the container — the image doesn't ship
   `tests/`, so `docker compose exec backend pytest` collects nothing.
3. The `qdrant` image ships no curl or wget; its healthcheck probes the port through
   bash's `/dev/tcp`.

**Verified on a cold `down` → `up --build`:** all 7 services boot, migrations reach
`0004 (head)`, `/health` ok, dashboard on :3000, **zero tracebacks** across all services,
and `down` leaves no containers or networks behind.

---

## 21. What I'd Improve Next

**In priority order** — the ordering is itself the answer, because it shows you weight
security and correctness above features.

1. **JWT auth + RBAC.** The blocking gap. `reviewer_name` must come from a verified token,
   not a request body. Roles: viewer (read), reviewer (approve), admin. Ideally approval
   authority scales with refund amount.
2. **Idempotency keys on `POST /tickets`.** A client retry currently creates a second
   ticket and a second workflow.
3. **A dead-letter stream.** Failed jobs are ACKed (correctly — an unacked poison job
   redelivers forever) but then only exist in logs. They should land somewhere requeueable.
4. **Server-Sent Events for the trace.** Polling at 2s is fine but SSE would drop the
   dashboard's request volume and feel instant. SSE over WebSockets because the data is
   one-directional.
5. **Prompt/tool-loop tuning with measurement.** Get the billing agent from five tool
   calls to two, with an eval set to prove quality didn't regress.
6. **Retention and partitioning** for audit, trace and checkpoint tables.
7. **An LLM eval harness.** The one thing the 400 tests cannot cover: golden tickets with
   expected intents, risk levels and HITL decisions, run against the real model in CI to
   catch prompt regressions.
8. **Circuit breaker on MCP.** Retry handles transient failure; a breaker would stop
   hammering a service that's genuinely down.
9. **Postgres in CI.** Two real bugs (row fan-out, `now()` semantics) were invisible to
   SQLite.
10. **PII redaction in the knowledge path**, if ingested docs ever contain customer data.

---

## 22. Interview Questions by Module, With Ideal Answers

### 22.1 Architecture

**Q: Walk me through what happens when a ticket arrives.**

Trace it end to end (§3.2) and land on the two boundaries: the API returns `202` after
persisting and queuing but before any reasoning; and the graph returns state while the
runner performs all writes. If you only say "it calls some agents", you've said nothing.

**Q: Why separate the dispatcher from the API?**

A workflow takes ~20 seconds, nearly all of it LLM inference. In-process, that occupies a
worker, dies on restart, and couples reasoning capacity to request capacity. Separate: the
API stays millisecond-fast, workflows survive an API deploy, reasoning scales
independently via consumer groups, and — the security benefit — the internet-facing
service holds no LLM credentials.

**Q: Why don't the graph nodes write to the database?**

Because checkpoint-resume **re-executes node bodies**. The HITL node body runs twice per
approval: once to pause (`interrupt()` raises), once to record (`interrupt()` returns).
If nodes wrote to the DB, every resume would duplicate those writes. Nodes return state;
the runner, which knows whether this is a fresh run or a resume, writes exactly once.

**Q: What happens if the dispatcher crashes mid-workflow?**

The job was never ACKed, so the consumer group redelivers it to another consumer. The
checkpointer holds state as of the last completed node, so it resumes rather than
restarting. This is tested: `test_a_parked_workflow_survives_a_dispatcher_restart` builds
a *second* runner over the same checkpointer and completes the workflow.

---

### 22.2 LangGraph

**Q: What is a reducer and why do you need one?**

Three domain agents execute in a single superstep. Without a reducer, two branches writing
the same key is a conflict and LangGraph raises `InvalidUpdateError`. A reducer defines how
concurrent writes combine — `operator.add` appends, `merge_dicts` merges key-by-key.
`current_node` deliberately has *no* reducer, which means only nodes running alone in a
superstep may write it. That's an invariant a unit test enforces by reading the state
annotations directly.

**Q: How does human-in-the-loop actually work?**

`interrupt()` raises `GraphInterrupt` out of `ainvoke` **after** the checkpoint is written.
The runner catches it and parks the run as `waiting_for_hitl`, having already persisted the
risk packet. `POST /approvals/{id}` audits the decision, flips the run to `running`, and
enqueues a `resume` job — **the API never runs the graph**. The dispatcher resumes with
`Command(resume={...})`, and this time `interrupt()` *returns* the decision. `workflow_id`
is the `thread_id`, which is how LangGraph finds the checkpoint.

**Q: Why is the Task Planner not an LLM?**

Reproducibility. Identical Supervisor output must produce a byte-identical plan, or a
resumed workflow could take a different path than the one that was checkpointed and the
audit trail would describe a run that never happened. Same argument for the Aggregator,
Risk Engine and Dispatcher: an LLM in the governance path makes approvals unauditable.
They also measure 0–1ms, so determinism costs nothing.

---

### 22.3 MCP

**Q: Why MCP instead of just calling functions?**

Give the honest version (§4). It converts the agent boundary from a code convention into
a network boundary, and centralises audit/timeout/error-normalisation for all 12 tools in
one unavoidable place. Then concede the cost: a network hop and a service to operate, which
is only worth it when tools are shared across teams or you must *prove* the reasoning layer
had no data access.

**Q: What happens when a tool times out?**

`run_tool` wraps every call in `asyncio.timeout`. Timeout → a structured
`{"code": "timeout"}` dict, plus an audit row marked failed. The retry layer retries only
`timeout` and transport errors — max 3, exponential backoff. Exhaustion degrades to
`{"code": "unavailable"}` and **never raises**, so one flaky tool can't kill a workflow that
might still resolve on partial information. `invalid_input` and `not_found` return
verbatim, unretried, so the LLM can correct its own call.

**Q: How do you stop an agent seeing another customer's data?**

Today: tool arguments are validated and the customer id comes from the workflow's own
ticket, not from the model. **But there is no authorisation layer** — nothing stops a
hallucinated invoice id from resolving. The fix is scoping every MCP call to the workflow's
customer server-side, which I'd implement alongside auth. Don't oversell this one.

---

### 22.4 RAG

**Q: How did you pick the score threshold?**

By measuring. bge cosine scores floor around 0.5 *even for unrelated text*, so a naive 0.2
threshold means the insufficient-information guard never fires. Measured on the seed
corpus: relevant ≥0.7, nonsense ≤0.52. 0.6 sits in the gap. The general lesson: a
similarity threshold is a property of the embedding model, so it must be measured against
your corpus, not copied.

**Q: What if Qdrant is down?**

The retriever raises, the exception propagates, and the MCP runtime audits it as a failure —
deliberately. The service must **never** convert an outage into `insufficient_information`,
because that would tell the customer "we have no refund policy" when the truth is "our
search is broken". One is a visible incident; the other is a silently wrong answer.

**Q: Why one collection instead of one per document type?**

Doc type is a payload field filtered with `MatchAny`. Three collections would mean three
schemas to maintain and would make cross-cutting search impossible. Adding a doc type is a
payload value, not a migration.

---

### 22.5 Governance

**Q: How do you decide something needs a human?**

Six factors (§10.1); the worst sets the level; high always forces HITL. The subtle part:
a refund amount only counts if *the same agent* also reported eligibility — otherwise a
merely looked-up invoice reads as money leaving and every billing enquiry escalates.

**Q: A 49-dollar refund escalated to a human. Is that a bug?**

No — and this is a good question to answer precisely. The Policy Agent returned
`approved=False` at confidence 0.50, tripping three factors at once. The governance path
worked as specified; the *tuning* is conservative. The fix is `HITL_CONFIDENCE_THRESHOLD`
or the Policy prompt — **not** weakening the Risk Engine. Never fix a governance complaint
by making governance weaker.

**Q: What if the approval payload is malformed?**

`parse_decision` treats anything unparseable as **rejection**. An unreadable decision is
never consent. Fail closed on the money-moving path.

---

### 22.6 Data & Testing

**Q: Why is `sequence` a column instead of ordering by timestamp?**

Parallel agents finish in the same superstep and Postgres' `now()` is transaction-scoped,
so they share `created_at` exactly; `id` is a random UUID4. Ordering by timestamp is
therefore random for concurrent rows. This also produced a genuinely instructive test
failure (§11.2B).

**Q: What do your tests NOT cover?**

Model quality. `ScriptedLLM` proves the wiring — routing, reducers, interrupt/resume, audit
writes — but no offline test proves Groq behaves well. That needs an eval harness against
the real model, which is item 7 on the improvements list. Also: SQLite hid two
Postgres-specific bugs, so Postgres in CI is item 9.

**Q: Why fake Redis instead of a real one in tests?**

So the suite runs anywhere with no services. `FakeRedisStream` implements XADD/XREADGROUP/
XACK plus consumer groups **and a pending set** — the pending set isn't gold-plating,
it's the only way to assert the "ACK even failed jobs" policy.

---

## 23. Questions That Expose Shallow Understanding

These are the ones that catch people who memorised a diagram. Each has a trap.

**"Just add a node that saves to the database — why is that hard?"**
*Trap:* it sounds trivial. *Answer:* node bodies re-execute on resume, so a DB write inside
a node duplicates on every approval. Persistence belongs in the runner, which knows the
difference between a run and a resume.

**"Your agents run in parallel. What if two write the same state key?"**
*Trap:* "it's fine, LangGraph merges." *Answer:* it is **not** fine by default —
LangGraph raises `InvalidUpdateError` unless the key carries a reducer. `current_node` has
none deliberately. And even with a reducer, a node returning a spread of prior state
double-appends.

**"Why not let the Policy Agent look things up itself?"**
*Trap:* "more data is better." *Answer:* it judges the other agents' results. If it gathers
its own evidence it can contradict them using data they never saw, and conflict resolution
becomes incoherent. Its job is adjudication, not investigation.

**"Retry the failed tool call — why not just retry everything?"**
*Trap:* retry sounds universally safe. *Answer:* retrying `not_found` is pointless (the
record won't appear) and retrying `invalid_input` is harmful — it re-sends bad arguments
and the model never learns to fix them. Returning the error verbatim lets the LLM correct
its own call.

**"Your dashboard shows a risk score. Where does it come from?"**
*Trap:* any vague answer. *Answer:* a real JSON column, `workflow_runs.risk_assessment`,
written by the runner from the graph's own output. It was **originally** string-parsed out
of a log line, which I rejected — re-wording a log would silently blank the risk shown to
someone approving a refund. Governance data is never parsed from prose.

**"You ACK failed jobs. Isn't that losing work?"**
*Trap:* sounds like a bug. *Answer:* the outcome is already persisted as failed in
`workflow_runs` and `audit_logs`. Leaving it unacked means infinite redelivery of a poison
job. The real gap is that there's no dead-letter stream — improvement 3.

**"How fast is it? Where did you optimise?"**
*Trap:* claiming optimisations you didn't measure. *Answer:* give the per-node table.
~99% is Groq inference; the deterministic nodes are 0–1ms. The one visible inefficiency is
five tool calls for one invoice question, which is prompt behaviour, and I deliberately
left it rather than guessing at a behavioural change. What I added was the instrumentation
to see it.

**"Is this production-ready?"**
*Trap:* saying yes. *Answer:* no — there is no authentication anywhere. Anyone reaching
port 3000 can approve any paused workflow. Architecturally it's sound and observable, but
that gap is blocking, and it's first on the improvement list.

---

## 24. Common Follow-Ups With Strong Answers

**"How would you add a new agent?"**
Add the enum member, prompt, and tool bindings in `AGENT_TOOL_NAMES`; create the node with
`make_domain_agent_node`; register it with `add()` in `build_workflow_graph` (tracing is
automatic); add it to `route_after_planner` and to the frontend `PIPELINE`. It must write
only reduced keys. Roughly 30 lines because the factory and the state contract already
exist.

**"How would you add a new MCP tool?"**
A `_TOOL_SPECS` entry with a Pydantic arg schema, a service method with the business logic,
and a thin wrapper calling `run_tool`. Auditing, timeout, error translation and tracing come
free. Then bind it to whichever agent should have it — that binding is the authorisation
decision.

**"Could you swap Groq for OpenAI?"**
One file. `app/graph/llm.py` is the only place credentials are read and the only place a
model is constructed. Every agent receives an injected model. Tests already inject a fake.

**"How do you handle a customer with two subscriptions?"**
Correctly now, after a bug. Both the tier and latest-workflow lookups are correlated scalar
subqueries with a deterministic tiebreak. They used to be plain outer joins, which returned
a ticket twice while `total` said 1 (§11.4). Always test a to-many join with two children.

**"What if two reviewers approve simultaneously?"**
The second gets a `409` — the service checks the run is `waiting_for_hitl` before acting.
The check and the status flip are in one transaction, so it's safe. Note the ordering
subtlety: the status flip is *flushed* but committed only after the enqueue succeeds, so a
Redis failure rolls the whole thing back and leaves the run reviewable rather than silently
unpaused.

**"Why 92% coverage and not 100%?"**
The uncovered lines are mostly process entrypoints (`dispatcher/main.py`), the real
checkpointer, and the Groq factory — code that only runs against real infrastructure.
Chasing 100% would mean testing that `asyncio.run` calls a function. The E2E suite covers
83–100% of the code that actually makes decisions.

---

## 25. Rebuilding From Scratch: The Thought Process

If asked "how would you approach this again", the answer is not the phase list — it's the
reasoning that produced it.

### Step 1 — Establish the invariants before writing code

Four constraints, decided first, that everything else follows from:

1. Reasoning is separate from execution.
2. Agents never touch the outside world.
3. Every state change is checkpointed and every business action is audited.
4. Governance is deterministic.

These are not style preferences. They're what makes the system explainable to an auditor,
and they're cheap to hold from day one and expensive to retrofit.

### Step 2 — Build in dependency order, verifying each layer live

The eight phases weren't arbitrary; each one is only testable once its predecessor is real:

1. **Persistence + API.** Schema, migrations, `POST /tickets` → 202 + queue. No AI.
2. **Graph skeleton.** GraphState with reducers *from the start*, Supervisor, deterministic
   planner. Retrofitting reducers means revisiting every node.
3. **MCP server.** Tools before agents, so the agents have something real to call.
4. **Agents + ToolNode.** Now the boundary can be enforced, because MCP exists.
5. **RAG.** Knowledge tools were stubbed in phase 3 and their contract didn't change here —
   only the implementation behind it.
6. **Governance + dispatcher.** Aggregator, Risk Engine, HITL, checkpointer, queue consumer.
   The graph is finally wired into the system.
7. **Dashboard.** Only meaningful once there are workflows to watch.
8. **Observability, E2E, docs.**

**Verify each phase against the running stack, not just the test suite.** Phases 3, 6, 7 and
8 each turned up a defect that unit tests could not have found: `421` from DNS-rebinding
protection, the redis socket-timeout collision, cold-start embedding timeouts, row fan-out.
Every one required real infrastructure.

### Step 3 — What I'd do differently

- **Postgres in CI from phase 1.** SQLite hid two real bugs.
- **`sequence` on `agent_execution_logs` from the start.** I added it in migration 0004
  after discovering timestamps can't order concurrent rows — predictable in hindsight.
- **Auth in phase 1, not "later".** It's now the single blocking gap, and retrofitting
  identity through an approvals flow is harder than starting with it.
- **An eval harness alongside the first agent.** I have 400 tests that prove the wiring and
  zero that prove prompt quality; prompt regressions are currently invisible.
- **Keep the phase discipline.** Not implementing future phases early is what kept each
  layer verifiable in isolation. That part I'd repeat exactly.

### Step 4 — The one-sentence version

> Build the deterministic skeleton first, make the boundary between reasoning and execution
> physical rather than conventional, checkpoint everything, and put a deterministic
> governance layer between the model and anything irreversible.

---

## Appendix A — Numbers to Know Cold

| Metric | Value |
|---|---|
| Tests / coverage | 400 passing, 92% |
| Test files | 27 (E2E: 21 tests in `test_e2e.py`) |
| Python modules | 86 |
| Migrations | 4 (`0004` is head) |
| Docker services | 7 |
| Graph nodes | **11** in the definition; a single run executes fewer (the planner fans out to only the domain agents a ticket needs) |
| MCP tools | 12, across 4 namespaces |
| Agents | 6 LLM-driven (Supervisor, Billing, Account, Technical, Policy, Response) |
| Deterministic nodes | 5 (Planner, Aggregator, Risk Engine, HITL, Dispatcher) |
| Embedding model | `BAAI/bge-small-en-v1.5`, 384-dim |
| RAG threshold | 0.6 (relevant ≥0.7, nonsense ≤0.52 measured) |
| Risk scores | low 0.2 / medium 0.5 / high 0.9 |
| HITL thresholds | refund 1000.0, confidence 0.6 |
| Max tool rounds | 8 |
| Retry policy | 3 attempts, exponential backoff, timeouts only |
| Poll intervals | 4s lists, 2s trace |
| Slowest node measured | billing_agent 11920ms (5 tool calls) |
| Total workflow measured | ~19.4s, ~99% LLM inference |

## Appendix B — Six Sentences That Signal Depth

1. "Node bodies re-execute on resume, so persistence lives in the runner, not the graph."
2. "Any key two parallel agents might write needs a reducer, or LangGraph raises
   `InvalidUpdateError`."
3. "Governance data is never parsed from prose — it's a column, written from the graph's
   own output."
4. "A policy *rejection* continues the workflow; a policy *failure* ends it. No verdict must
   never produce a customer reply."
5. "The RAG threshold is 0.6 because bge scores floor at 0.5 — measured, not copied."
6. "There's no authentication anywhere; that's the blocking gap before any shared
   deployment."
