# Software Requirements Specification (SRS)

# AgentFlow AI
## Enterprise Multi-Agent Customer Operations Platform for B2B SaaS

**Version:** 2.0

**Status:** Design Phase

**Author:** Nimish Somani

**Technology Stack**
- Python 3.11+
- FastAPI
- LangGraph
- Groq API
- PostgreSQL
- Redis
- Qdrant
- MCP (Model Context Protocol)
- SQLAlchemy
- Docker Compose
- React
- TailwindCSS
- OpenTelemetry

---

# 1. Introduction

## 1.1 Purpose

AgentFlow AI is an enterprise-inspired multi-agent workflow platform designed to automate customer support operations for Business-to-Business (B2B) Software-as-a-Service (SaaS) companies.

Unlike traditional AI chatbots that generate responses directly from a Large Language Model (LLM), AgentFlow AI decomposes customer requests into structured workflows executed by multiple specialised AI agents. Each agent is responsible for a specific business capability such as billing, customer account management, technical support, or policy validation.

The platform combines deterministic workflow orchestration, Retrieval-Augmented Generation (RAG), Model Context Protocol (MCP), and Human-in-the-Loop (HITL) approvals to produce reliable, explainable, and enterprise-ready customer support resolutions.

This document serves as the complete engineering specification for the project and will guide implementation using AI-assisted development tools such as Cursor, Claude Code, Gemini CLI, and GitHub Copilot.

---

# 1.2 Business Problem

Modern B2B SaaS companies receive thousands of customer support requests every day.

Examples include:

- Duplicate subscription charges
- Locked enterprise dashboards
- API authentication failures
- Subscription upgrades
- Account permission issues
- Refund requests
- Feature activation requests
- Product troubleshooting

Today, these requests typically require multiple departments to collaborate.

Example:

Customer Ticket

↓

Customer Support Team

↓

Billing Team

↓

Account Management

↓

Engineering Team

↓

Manager Approval

↓

Customer Response

This manual process introduces:

- High operational costs
- Long response times
- Inconsistent customer experiences
- Human errors
- Limited scalability

Although modern LLMs can generate fluent responses, they cannot safely execute enterprise workflows without structured planning, governance, tool integration, and business rule enforcement.

---

# 1.3 Proposed Solution

AgentFlow AI introduces an enterprise-grade multi-agent architecture where specialised AI agents collaborate to resolve customer support requests.

Instead of relying on a single LLM, the platform follows a deterministic workflow:

1. Receive customer ticket.
2. Analyse customer intent.
3. Generate an execution plan.
4. Delegate work to specialised agents.
5. Access enterprise systems securely through MCP.
6. Retrieve organisational knowledge using RAG.
7. Aggregate all agent outputs.
8. Evaluate organisational policies and risk.
9. Request human approval for sensitive actions.
10. Generate a professional customer response.
11. Dispatch the response to the appropriate support channel.

The system separates reasoning from execution, making workflows more reliable, explainable, auditable, and scalable.

---

# 2. Project Vision

To build a production-inspired enterprise AI platform capable of orchestrating multiple specialised AI agents that collaboratively resolve customer support tickets while maintaining security, governance, explainability, and operational reliability.

The project demonstrates modern enterprise AI engineering concepts including:

- Multi-Agent Systems
- Workflow Orchestration
- Agent Planning
- MCP-Based Tool Calling
- Retrieval-Augmented Generation
- Human-in-the-Loop Governance
- Durable Workflow Execution
- Enterprise Observability

---

# 3. Project Objectives

The platform must:

✓ Automate customer support workflows

✓ Use multiple specialised AI agents

✓ Execute deterministic workflows using LangGraph

✓ Securely access enterprise tools through MCP

✓ Retrieve company knowledge using RAG

✓ Maintain workflow state throughout execution

✓ Support human approvals for sensitive actions

✓ Handle partial failures gracefully

✓ Produce explainable execution traces

✓ Be fully containerised using Docker Compose

✓ Be deployable on a local development environment

---

# 4. Project Scope

## In Scope

The system SHALL provide:

### Customer Ticket Processing

- Ticket ingestion
- Customer identification
- Ticket classification
- Priority assignment

### Workflow Planning

- Intent understanding
- Task decomposition
- Agent selection
- Execution planning

### Multi-Agent Collaboration

Specialised agents:

- Supervisor Agent
- Billing Agent
- Account Agent
- Technical Support Agent
- Policy Agent
- Response Agent

### Enterprise Tool Integration

Using MCP Servers: Enterprise MCP Server
(tool namespaces)
- Billing 
- Customer Account 
- Knowledge 
- Ticket 

### Knowledge Retrieval

- Company documentation
- FAQs
- Troubleshooting guides
- Product documentation
- Refund policies
- SLA documents

### Governance

- Risk scoring
- Policy validation
- Human approval workflow
- Audit logging

### Response Delivery

- Customer response generation
- Internal notes
- Ticket updates
- Webhook dispatch


### Database Seeding
Automated generation of mock B2B SaaS users, subscriptions, and invoices for local testing.

---

## Out of Scope

The following are intentionally excluded from Version 1.0:

- Multi-tenancy
- Kubernetes deployment
- Real Stripe integration
- Salesforce integration
- Zendesk integration
- Slack integration
- Voice support
- Multi-language support
- Mobile application
- Fine-tuned language models
- Autonomous agent creation
- Dynamic agent discovery
- Distributed microservices

These features may be considered future enhancements.

---

# 5. Target Users


Primary users include:

### Customer Support Teams

Review AI-generated responses and approve sensitive actions.

### Operations Teams

Monitor workflow execution and system health.

### Engineering Teams

Maintain enterprise integrations and knowledge bases.

### Platform Administrators

Manage workflows, approvals, and observability.

### Target Users
The React frontend is exclusively a 'Support Dashboard / Admin UI' used for monitoring tickets and providing Human-in-the-Loop (HITL) approvals. It is not a customer-facing chat portal.

---

# 6. Functional Requirements

The system SHALL:

FR-001
Accept customer support tickets through REST APIs.

FR-002
Store ticket metadata.

FR-003
Analyse customer intent.

FR-004
Generate an execution plan.

FR-005
Delegate tasks to specialised agents.

FR-006
Execute multiple agents concurrently whenever possible.

FR-007
Access enterprise systems exclusively through MCP servers.

FR-008
Retrieve organisational knowledge using RAG.

FR-009
Aggregate outputs from all executed agents.

FR-010
Detect conflicting agent recommendations.

FR-011
Calculate workflow risk.

FR-012
Pause execution for human approval when required.

FR-013
Resume execution after approval.

FR-014
Generate customer-friendly responses.

FR-015
Dispatch responses through configurable output channels.

FR-016
Persist workflow state after every LangGraph node.

FR-017
Log all workflow activities.

FR-018
Record all tool calls.

FR-019
Support workflow retries after recoverable failures.

FR-020
Provide workflow status through REST APIs.

---

# 7. Non-Functional Requirements

## Performance

- Average workflow latency under 15 seconds
- Agent execution should support parallel processing
- API response time under 500 ms for ticket submission

---

## Reliability

- Durable execution using LangGraph checkpoints
- Automatic retry for transient failures
- Idempotent business operations

---

## Scalability

The architecture shall support adding new agents without modifying existing business logic.

---

## Security

- JWT Authentication
- Role-Based Access Control (RBAC)
- Input validation
- Secure environment variables
- MCP abstraction for enterprise tools

---

## Maintainability

- Modular architecture
- Clear separation of concerns
- Typed interfaces
- Comprehensive logging

---

## Observability

The system shall expose:

- Workflow traces
- Agent execution timelines
- Tool invocation history
- Error logs
- Latency metrics

using OpenTelemetry.

---

# 8. Technology Stack

| Layer | Technology |
|----------|------------|
| Programming Language | Python 3.11+ |
| Backend Framework | FastAPI |
| AI Workflow Engine | LangGraph |
| LLM Provider | Groq API |
| Embedding Model | BAAI/bge-small-en-v1.5 |
| Vector Database | Qdrant |
| Relational Database | PostgreSQL |
| Cache & Workflow Memory | Redis |
| Queue | Redis Streams |
| ORM | SQLAlchemy |
| Validation | Pydantic v2 |
| Tool Integration | Model Context Protocol (MCP) |
| Frontend | React |
| UI Framework | TailwindCSS |
| Observability | OpenTelemetry |
| Containerisation | Docker Compose |
| Testing | Pytest |

---

# 9. System Design Principles

The following principles govern the architecture.

### Principle 1

Reasoning must remain separate from execution.

---

### Principle 2

Agents never access enterprise systems directly.

All external operations must pass through MCP servers.

---

### Principle 3

Every workflow must be deterministic.

LLMs make decisions.

LangGraph controls execution.

---

### Principle 4

Every workflow state must be recoverable.

---

### Principle 5

Business logic must never exist inside API routes.

---

### Principle 6

Every component should have a single responsibility.

---

### Principle 7

Knowledge retrieval must always occur before generating customer responses.

---

### Principle 8

Sensitive actions must always pass through policy validation.

---

### Principle 9

Human approval must interrupt workflow execution rather than restarting it.

---

### Principle 10

Every action performed by the platform must be observable and auditable.

---

# 10. Repository Structure

```

agentflow-ai/

│

├── app/

│ ├── api/

│ ├── agents/

│ ├── graph/

│ ├── mcp/

│ ├── database/

│ ├── models/

│ ├── rag/

│ ├── services/

│ ├── dispatcher/

│ ├── observability/

│ ├── prompts/

│ ├── utils/

│ └── config/

│

├── frontend/

│

├── docs/

│

├── tests/

│

├── docker/

│

├── scripts/

│

├── docker-compose.yml

├── requirements.txt

├── README.md

└── SRS.md

```

---

# End of Part 1

The following section (Part 2) will define:

- Complete Enterprise Architecture
- Component Responsibilities
- End-to-End Workflow
- Sequence Diagrams
- LangGraph Workflow
- Interaction Between Agents
- MCP Communication Flow
- System Context Diagram

# 11. High-Level System Architecture

## 11.1 System Overview

AgentFlow AI follows an event-driven, workflow-oriented architecture designed around deterministic orchestration rather than autonomous agents making uncontrolled decisions.

The platform separates:

- Request Ingestion
- Workflow Planning
- Workflow Execution
- Enterprise Tool Access
- Governance
- Response Generation
- Observability

The Large Language Model (LLM) is responsible only for reasoning.

LangGraph is responsible for orchestration.

MCP is responsible for enterprise tool access.

PostgreSQL stores business data.

Redis stores runtime workflow memory.

Qdrant stores enterprise knowledge.

---

## 11.2 High-Level Architecture

```text
                         Customer

                            │

                            ▼

                  FastAPI API Gateway

                            │

                    Redis Streams Queue

                            │

                            ▼

                  LangGraph Workflow Engine

                            │

                Supervisor Agent (LLM)

                            │

                     Task Planner

                            │

            Generates Execution Plan

                            │

             Parallel Agent Execution

      ┌──────────┬────────────┬────────────┬────────────┐

      ▼          ▼            ▼            ▼

 Billing     Account      Technical     Policy

 Agent        Agent         Agent        Agent

      └──────────┬────────────┬────────────┘

                 ▼

          Enterprise MCP Layer

      ┌──────────┬──────────┬──────────┬──────────┐

      ▼          ▼          ▼          ▼

 Billing      Account   Knowledge    Ticket

   MCP          MCP         MCP         MCP

      └──────────┬──────────┬──────────┘

                 ▼

        Enterprise Systems Layer

  PostgreSQL

  Billing Service

  Ticket Database

  Qdrant Vector Database

                 ▼

          Results Aggregator

                 ▼

         Conflict Resolver

                 ▼

        Policy & Risk Engine

                 │

        High Risk Decision?

          │            │

         Yes          No

          │            │

          ▼            ▼

 Human Approval     Response Agent

          │            │

          └──────┬─────┘

                 ▼

             Dispatcher

                 ▼

     Customer Portal / Email / Webhook

```

---

# 12. Layered Architecture

The platform consists of seven logical layers.

Each layer has a single responsibility.

---

## Layer 1

### Presentation Layer

Responsibilities

- Receive customer tickets
- Validate API requests
- Return workflow status
- Receive approval decisions

Components

- FastAPI
- React Dashboard

No business logic is allowed in this layer.

---

## Layer 2

### Workflow Orchestration Layer

Responsibilities

- Manage workflow lifecycle
- Schedule execution
- Resume interrupted workflows
- Retry failed nodes
- Store checkpoints

Technology

LangGraph

---

## Layer 3

### Agent Layer

Responsibilities

Reason about business problems.

Generate structured outputs.

Never perform database operations.

Never execute SQL.

Never call REST APIs.

Never modify enterprise systems directly.

Agents only communicate with MCP.

Agents

- Supervisor Agent
- Billing Agent
- Account Agent
- Technical Agent
- Policy Agent
- Response Agent

---

## Layer 4

### MCP Layer

Responsibilities

Expose enterprise capabilities as secure tools.

Hide implementation details.

Provide stable interfaces.

Technologies

Official Python MCP SDK

MCP Servers

Enterprise MCP Server

---

## Layer 5

### Enterprise Services Layer

Responsibilities

Provide business services.

Contains

Billing Service

Customer Database

Knowledge Base

Ticket Service

---

## Layer 6

### Data Layer

Contains

PostgreSQL

Redis

Qdrant

Each database has a single responsibility.

---

## Layer 7

### Observability Layer

Responsibilities

Logging

Tracing

Metrics

Audit Logs

Workflow Monitoring

Technologies

OpenTelemetry

Python Logging

---

# 13. End-to-End Workflow

The platform executes every ticket using the following sequence.

---

## Step 1

Customer submits a ticket.

Example

"I was charged twice for my enterprise subscription and my dashboard is locked."

---

## Step 2

FastAPI validates

- Request schema
- Authentication
- Rate limits

If valid

Create Workflow ID

Store metadata

Push workflow into Redis Stream.

Return

HTTP 202 Accepted

---

## Step 3

LangGraph starts execution.

Creates initial Graph State.

Loads conversation memory.

---

## Step 4

Supervisor Agent

Responsibilities

Understand intent.

Identify affected business domains.

Output

Customer Intent

Affected Systems

Required Business Functions

---

## Step 5

Task Planner

Creates Execution Plan.

Example

```text
Task 1

Verify invoice

↓

Task 2

Verify subscription

↓

Task 3

Validate refund policy

↓

Task 4

Generate response
```

The execution plan is stored inside GraphState.

---

## Step 6

LangGraph schedules parallel execution.

Example

Billing Agent

||

Account Agent

||

Policy Agent

The Technical Agent only executes if required.

---

## Step 7

Each Agent performs reasoning.

Example

Billing Agent

↓

Needs invoice

↓

Calls Enterprise MCP Server

↓

Enterprise MCP Server

↓

Billing Service

↓

PostgreSQL

↓

Returns invoice

Billing Agent never knows where data came from.

---

## Step 8

Technical Agent

If documentation is required

↓

Knowledge MCP

↓

Qdrant

↓

Retrieve documentation

↓

Return relevant context

---

## Step 9

Results Aggregator

Collects

Billing Result

Account Result

Technical Result

Policy Result

Produces unified workflow context.

---

## Step 10

Conflict Resolver

Checks

Contradictory recommendations

Missing information

Failed agents

Produces

Resolved workflow output.

---

## Step 11

Policy & Risk Engine

Calculates

Risk Score

Business Rule Compliance

Permission Checks

Confidence Score

Decision

Human Approval Required?

---

## Step 12

If approval required

LangGraph interrupts execution.

Workflow checkpoint saved.

Admin reviews decision.

Workflow resumes from checkpoint.

---

## Step 13

Response Agent

Generates

Customer response

Internal notes

Resolution summary

---

## Step 14

Dispatcher

Routes response.

Possible outputs

Customer Portal

Webhook

Email

Ticket System

---

## Step 15

Workflow Complete

Status updated

Metrics recorded

Audit log written

Checkpoint archived

if a webhook fails, it should log the failure but NOT crash the workflow. The ticket resolution is already complete at that point.

---

# 14. Component Responsibilities

## FastAPI Gateway

Responsibilities

- Validate requests
- Create workflow
- Queue jobs
- Return status

Must never call an LLM.

---

## Supervisor Agent

Responsibilities

- Understand request
- Decide required business capabilities
- Invoke Task Planner

Must never access enterprise tools.

---

## Task Planner

Responsibilities

Generate ordered execution plan.

Determine

Dependencies

Parallel tasks

Execution priority

Must never call MCP.

---

## LangGraph

Responsibilities

Workflow orchestration

Checkpointing

Parallel execution

Interrupts

Retries

State persistence

---

## Domain Agents

Responsibilities

Reason over domain knowledge.

Request enterprise tools.

Return structured AgentResult.

Must never directly access databases.

Agents evaluate state and return a standard tool_call object. The LangGraph orchestration layer is responsible for routing this request to the MCP client (ToolNode) and returning the result back to the Agent.

---

## MCP Servers

Responsibilities

Provide secure enterprise tool access.

Translate tool requests into

SQL

REST

Vector Search

Business Services

---

## Results Aggregator

Responsibilities

Merge all successful AgentResults.

Collect failed agent information.

Produce shared workflow context.

---

## Conflict Resolver

Responsibilities

Detect conflicting recommendations.

Prioritise business rules.

Prepare final execution state.

---

## Policy & Risk Engine

Responsibilities

Evaluate

Business Policies

Confidence

Permissions

Sensitive Operations

Outputs

Risk Score

Requires HITL

Approval Reason

---

## Human Approval

Responsibilities

Approve

Reject

Request Manual Review

Workflow resumes from checkpoint.

---

## Response Agent

Responsibilities

Generate

Professional response

Internal summary

Resolution explanation

---

## Dispatcher

Responsibilities

Deliver response.

No reasoning.

No LLM.

Only routing.

---

# 15. Sequence Diagram

## Example

Duplicate Payment + Locked Dashboard

```text
Customer

    │

    ▼

FastAPI

    │

    ▼

Redis Queue

    │

    ▼

LangGraph

    │

    ▼

Supervisor

    │

    ▼

Task Planner

    │

 ┌──┴─────────────┐

 ▼                ▼

Billing       Account

 │                │

 ▼                ▼

Enterprise MCP  Enterprise MCP

 │                │

 ▼                ▼

PostgreSQL    PostgreSQL

 └──────┬─────────┘

        ▼

Results Aggregator

        ▼

Conflict Resolver

        ▼

Policy Engine

        │

Approval?

   │

 No

   │

   ▼

Response Agent

   ▼

Dispatcher

   ▼

Customer
```

---

# 16. Architectural Constraints

The following rules are mandatory.

1. Agents never access databases directly.

2. Agents never call REST APIs directly.

3. Every enterprise operation must use MCP.

4. Every workflow step must update GraphState.

5. Every node must be checkpointed.

6. Every failure must be recoverable.

7. Every agent returns structured data.

8. Every external request must have timeout handling.

9. Every workflow must be resumable.

10. Every business action must be auditable.

11. The entire system MUST be fully asynchronous. Use async def, httpx (instead of requests), asyncpg or SQLAlchemy[asyncio], and the async integrations for LangGraph and Redis.

---

# End of Part 2

The next section (Part 3) defines the implementation contracts:

- PostgreSQL Schema
- GraphState
- Execution Plan Model
- AgentResult Model
- Shared Context Model
- Redis Memory Model
- Knowledge Base Schema
- Pydantic Models

# 17. Data Architecture

## 17.1 Data Storage Overview

The platform uses multiple storage systems, each with a dedicated responsibility.

| Storage | Responsibility |
|----------|---------------|
| PostgreSQL | Business data, workflow checkpoints, audit logs |
| Redis | Runtime workflow memory, queues, execution context |
| Qdrant | Enterprise knowledge base for RAG |

Each storage component has a single responsibility and must never overlap with another.

---

# 18. PostgreSQL Database Schema

The relational database stores operational business data.

---

## 18.1 Users

Represents enterprise customers.

| Column | Type | Description |
|----------|------|------------|
| id | UUID | Primary Key |
| company_name | VARCHAR(255) | Customer organization |
| full_name | VARCHAR(255) | Primary contact |
| email | VARCHAR(255) | Unique email |
| account_status | ENUM | active, locked, suspended |
| role | ENUM | admin, member |
| created_at | TIMESTAMP | Creation timestamp |
| updated_at | TIMESTAMP | Last modification |

---

## 18.2 Subscriptions

Stores SaaS subscription details.

| Column | Type |
|----------|------|
| id | UUID |
| user_id | UUID (FK Users) |
| plan | ENUM(basic,premium,enterprise) |
| monthly_price | DECIMAL |
| renewal_date | DATE |
| subscription_status | ENUM(active,cancelled,expired) |

---

## 18.3 Invoices

Stores billing history.

| Column | Type |
|----------|------|
| id | UUID |
| user_id | UUID |
| amount | DECIMAL |
| currency | VARCHAR(10) |
| payment_status | ENUM(paid,pending,duplicate,refunded) |
| created_at | TIMESTAMP |

---

## 18.4 Support Tickets

Stores customer tickets.

| Column | Type |
|----------|------|
| id | UUID |
| customer_id | UUID |
| title | TEXT |
| description | TEXT |
| priority | ENUM(low,medium,high,critical) |
| status | ENUM(open,in_progress,resolved,closed) |
| created_at | TIMESTAMP |

---

## 18.5 Workflow Runs

Tracks every LangGraph execution.

| Column | Type |
|----------|------|
| workflow_id | UUID |
| ticket_id | UUID |
| workflow_status | ENUM(running,waiting_for_hitl,completed,failed) |
| current_node | VARCHAR |
| started_at | TIMESTAMP |
| completed_at | TIMESTAMP |

---

## 18.6 Agent Execution Logs

Stores execution history for every agent.

| Column | Type |
|----------|------|
| id | UUID |
| workflow_id | UUID |
| agent_name | VARCHAR |
| execution_time_ms | INTEGER |
| status | VARCHAR |
| tool_calls | INTEGER |
| created_at | TIMESTAMP |

---

## 18.7 Audit Logs

Stores critical business actions.

| Column | Type |
|----------|------|
| id | UUID |
| workflow_id | UUID |
| action | TEXT |
| performed_by | VARCHAR |
| timestamp | TIMESTAMP |

---

# 19. Redis Architecture

Redis is **NOT** a permanent database.

Redis stores temporary workflow information.

It contains

- Workflow Queue
- Conversation Memory
- Shared Context
- Execution State
- Temporary Cache

Redis should never store permanent customer records.

---

# 20. Knowledge Base

Knowledge is stored inside Qdrant.

Documents originate from

- FAQs
- Product Documentation
- SLA Documents
- Refund Policies
- Troubleshooting Guides
- Internal Runbooks

Knowledge ingestion is covered in Part 6.

---

# 21. LangGraph State

GraphState is the single source of truth during workflow execution.

Every LangGraph node receives the GraphState.

Every LangGraph node returns an updated GraphState.

No node should mutate state outside LangGraph.

```python
from typing import TypedDict, List, Dict, Optional, Literal, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from datetime import datetime
import operator

class ExecutionTask(TypedDict):
    task_id: str
    task_name: str
    assigned_agent: str
    priority: Literal["low","medium","high"]
    depends_on: List[str]
    status: Literal[
        "pending",
        "running",
        "completed",
        "failed",
        "skipped"
    ]

class AgentResult(TypedDict):
    agent_name: str
    status: Literal[
        "success",
        "failed",
        "skipped"
    ]
    summary: str
    confidence: float
    actions_taken: List[str]
    tool_calls: List[str]
    output_data: Dict

class GraphState(TypedDict):

    workflow_id: str

    ticket_id: str

    customer_id: str

    issue_text: str

    customer_tier: str

    ticket_priority: str

    execution_plan: List[ExecutionTask]

    completed_agents: List[str]

    current_node: str

    shared_context: Dict

    messages: Annotated[List[BaseMessage], add_messages]

    tool_history: List[str]

    risk_score: float

    requires_hitl: bool

    approval_status: Optional[str]

    workflow_status: str

    retry_count: int

    errors: List[str]

    final_response: Optional[str]

    # Use Annotated + operator.add so parallel agents append their results safely
    agent_results: Annotated[List[AgentResult], operator.add] 
    errors: Annotated[List[str], operator.add]
```

---

# 22. Execution Plan Model

The Task Planner generates an ordered execution plan.

```python
class ExecutionTask(TypedDict):

    task_id: str

    task_name: str

    assigned_agent: str

    priority: str

    depends_on: List[str]

    status: str
```

Example

```text
Task 1

Verify Invoice

↓

Billing Agent

Task 2

Verify Account

↓

Account Agent

Task 3

Validate Refund

↓

Policy Agent

Task 4

Generate Response

↓

Response Agent
```

---

# 23. Agent Result Contract

Every agent must return the same structure.

```python
class AgentResult(TypedDict):

    agent_name: str

    status: str

    confidence: float

    summary: str

    actions_taken: List[str]

    tool_calls: List[str]

    output_data: Dict
```

This allows the Results Aggregator to combine outputs consistently.

---

# 24. Shared Context

Shared Context is a structured object passed between agents.

It contains information already discovered.

Example

```python
shared_context = {

    "customer_name":"Alice",

    "subscription":"Enterprise",

    "invoice_status":"Duplicate",

    "dashboard_locked":True,

    "refund_allowed":True

}
```

Agents should read from Shared Context before calling MCP tools.

This avoids duplicate work.

---

# 25. Workflow Memory

Redis stores temporary execution memory.

Example

```python
workflow_memory = {

    "workflow_id":"wf_001",

    "current_node":"Billing Agent",

    "completed_nodes":[
        "Supervisor",
        "Planner"
    ],

    "retry_count":1,

    "last_checkpoint":"Billing Agent"

}
```

Memory expires after workflow completion.

---

# 26. Pydantic Request Models

## Ticket Submission

```python
class TicketRequest(BaseModel):

    customer_id: str

    subject: str

    description: str
```

---

## Ticket Response

```python
class TicketResponse(BaseModel):

    workflow_id: str

    status: str

    estimated_wait_time: int
```

---

## HITL Approval

```python
class ApprovalRequest(BaseModel):

    approved: bool

    reviewer_name: str

    comments: str
```

---

## Workflow Status

```python
class WorkflowStatus(BaseModel):

    workflow_id: str

    current_node: str

    workflow_status: str

    completed_agents: List[str]

    requires_hitl: bool
```
Note : All Pydantic models must include model_config = ConfigDict(from_attributes=True) to seamlessly parse SQLAlchemy ORM objects.

---

# 27. Enumerations

## Workflow Status

```text
pending

running

waiting_for_hitl

completed

failed
```

---

## Agent Status

```text
pending

running

completed

failed

skipped
```

---

## Ticket Priority

```text
low

medium

high

critical
```

---

## Risk Level

```text
low

medium

high
```

---

# 28. Data Ownership

Each component owns only its own data.

| Component | Owns |
|-----------|------|
| FastAPI | HTTP Requests |
| LangGraph | GraphState |
| Supervisor | Execution Plan |
| Agents | AgentResult |
| Results Aggregator | Combined Results |
| Risk Engine | Risk Score |
| Dispatcher | Delivery Status |
| PostgreSQL | Persistent Business Data |
| Redis | Runtime Memory |
| Qdrant | Enterprise Knowledge |

No component should modify another component's internal state directly.

Communication must occur through GraphState or MCP interfaces.

---

# 29. Data Flow Summary

```text
Customer Ticket

↓

FastAPI

↓

GraphState Created

↓

Supervisor

↓

Execution Plan

↓

Parallel Agents

↓

Agent Results

↓

Shared Context

↓

Results Aggregator

↓

Risk Engine

↓

Response Agent

↓

Dispatcher

↓

Workflow Completed
```

---

# End of Part 3

Part 4 defines every AI agent in detail.

Each agent will include:

- Responsibilities
- Inputs
- Outputs
- Prompt Strategy
- MCP Tools
- Failure Conditions
- Retry Policy
- Implementation Rules
- Example Input
- Example Output

This section will become the blueprint for implementing each LangGraph node.

# 30. Agent Specifications

## Common Rules

All agents MUST:

- Read GraphState.
- Return updates to GraphState only.
- Return the standard `AgentResult` contract.
- Use MCP tools for all external operations.
- Never access databases directly.
- Never execute HTTP requests.
- Never call another agent directly.
- Never modify another agent's output.

LangGraph Rule:

Every agent node returns a **state update dictionary**, for example:

```python
return {
    "agent_results": [billing_result],
    "messages": [ai_message]
}
```

---

## 30.1 Supervisor Agent

### Responsibility

- Understand customer intent
- Identify business domains
- Classify ticket priority

### Output

```python
{
    "intent": "Billing Issue",
    "domains": ["billing", "account"],
    "priority": "high"
}
```

LLM: ✅

MCP: ❌

---

## 30.2 Task Planner

A deterministic Python component.

Converts Supervisor output into an ordered `ExecutionTask` list.

LLM: ❌

MCP: ❌

---

## 30.3 Billing Agent

Responsibilities

- Verify invoices
- Detect duplicate payments
- Calculate refunds

Available MCP Tools

- billing_get_invoice()
- get_subscription()
- calculate_refund()

Returns

Standard `AgentResult`

---

## 30.4 Account Agent

Responsibilities

- Verify customer account
- Unlock dashboard
- Check permissions
- Update feature flags

Available MCP Tools

- get_customer()
- unlock_dashboard()
- update_feature_flag()

Returns

Standard `AgentResult`

---

## 30.5 Technical Agent

Responsibilities

- Retrieve documentation
- Search FAQs
- Search troubleshooting guides

Available MCP Tools

- knowledge_semantic_search()

Rules

- Never answer without retrieved context.
- Never hallucinate technical solutions.

Returns

Standard `AgentResult`

---

## 30.6 Policy Agent

Responsibilities

- Validate refund rules
- Check SLA
- Validate permissions
- Calculate workflow risk

Returns

```python
{
    "agent_name": "Policy Agent",
    "status": "success",
    "summary": "Refund approved. Risk is low.",
    "confidence": 0.98,
    "actions_taken": [
        "evaluated_refund_policy"
    ],
    "tool_calls": [],
    "output_data": {
        "approved": True,
        "risk": "low"
    }
}
```

---

## 30.7 Response Agent

Responsibilities

- Generate customer response
- Generate internal notes
- Generate resolution summary

Rules

- Uses only GraphState and AgentResults.
- Never calls MCP.
- Never queries databases.

Returns

Standard `AgentResult`

---

# 31. Enterprise MCP Server

The platform uses **one Enterprise MCP Server** exposing multiple tool namespaces.

```text
Enterprise MCP Server

├── Billing Tools
│   ├── get_invoice
│   ├── get_subscription
│   └── calculate_refund
│
├── Account Tools
│   ├── get_customer
│   ├── unlock_dashboard
│   └── update_feature_flag
│
├── Knowledge Tools
│   ├── semantic_search
│   ├── search_policy
│   └── search_runbook
│
└── Ticket Tools
    ├── get_ticket
    ├── update_ticket
    └── add_internal_note
```

Backend

```text
Enterprise MCP Server

↓

Billing Service

↓

Customer Service

↓

Ticket Service

↓

Qdrant

↓

PostgreSQL
```

### Implementation Rule

Agents never execute HTTP requests.

The Agent LLM binds to MCP tools and generates a **tool_call**.

A LangGraph **ToolNode** intercepts the tool call, invokes the Enterprise MCP client, executes the requested tool, and returns the resulting **tool_message** back into the workflow.

Only the ToolNode communicates with the MCP server.

---

# 32. Knowledge Pipeline

```text
PDF / Markdown / FAQ / Policies

↓

Chunking

↓

Embeddings

↓

Qdrant
```

Embedding Model

- BAAI/bge-small-en-v1.5

Knowledge is indexed offline.

Agents access knowledge only through the Enterprise MCP Server.

---

# 33. RAG Flow

```text
Technical Agent

↓

Tool Call

↓

LangGraph ToolNode

↓

Enterprise MCP Server

↓

Qdrant

↓

Top-K Results

↓

Tool Message

↓

Technical Agent

↓

Grounded Response
```

Rules

- Retrieve before generation.
- Return citations when available.
- If no relevant context exists, respond with insufficient information.

---

# 34. Communication Rules

Allowed

```text
Supervisor
    ↓
Task Planner
    ↓
LangGraph
    ↓
Agent
    ↓
LangGraph ToolNode
    ↓
Enterprise MCP Server
    ↓
Services / Databases
```

Forbidden

- Agent → Database
- Agent → HTTP API
- Agent → Agent
- FastAPI → LLM
- Response Agent → MCP

---

# 35. Failure Handling

Recoverable

- MCP timeout
- Vector search failure
- Temporary database failure

Action

- Retry (max 3)
- Exponential backoff
- Continue with partial results where safe

Non-Recoverable

- Invalid ticket
- Missing customer
- Corrupted workflow

Action

- Stop workflow
- Update GraphState
- Persist audit log

# 36. REST API

## POST /tickets

Create a new support workflow.

Request

```json
{
  "customer_id": "uuid",
  "subject": "Duplicate payment",
  "description": "I was charged twice."
}
```

Response

```json
{
  "workflow_id": "wf_001",
  "status": "accepted"
}
```
Implementation Rule: This endpoint must return HTTP 202 Accepted immediately. The LangGraph workflow must be triggered using fastapi.BackgroundTasks to run asynchronously.

---

## GET /workflows/{workflow_id}

Returns current workflow status.

Response

```json
{
  "workflow_id": "wf_001",
  "status": "running",
  "current_node": "Billing Agent",
  "requires_hitl": false
}
```

---

## POST /approvals/{workflow_id}

Resume a paused workflow.

```json
{
  "approved": true,
  "reviewer": "Support Manager",
  "comments": "Refund approved."
}
```

---

## GET /tickets/{ticket_id}

Return ticket details and resolution.



---

# 37. LangGraph Workflow

```text
START

↓

Supervisor

↓

Task Planner

↓

Billing Agent (optional)
      │
Account Agent (optional)
      │
Technical Agent (optional)
      │
Policy Agent (always)

↓

Results Aggregator

↓

Risk Engine

↓

Approval Needed?

├── Yes → HITL → Resume
└── No

↓

Response Agent

↓

Dispatcher

↓

END
```

Rules

- Planner determines which agents execute.
- Independent agents run in parallel.
- Every node updates GraphState.
- Workflow checkpoints after every node.

---

# 38. Human-in-the-Loop (HITL)

Approval is required for:

- Refund above configured threshold
- Account suspension
- Permission changes
- Low confidence (< configured threshold)
- High workflow risk

When triggered:

1. Save checkpoint.
2. Update workflow status to `waiting_for_hitl`.
3. Pause execution.
4. Wait for approval.
5. Resume from checkpoint.

Implementation Rule: Use the workflow_id as the LangGraph thread_id inside the RunnableConfig. The POST /approvals endpoint will use this thread_id to fetch the current state, update it, and call graph.ainvoke(Command(resume=True)) to unpause.

---

# 39. Risk Engine

Inputs

- AgentResults
- Confidence scores
- Policy result
- Workflow context

Outputs

```python
{
    "risk_level": "low",
    "requires_hitl": False
}
```

Decision Factors

- Financial impact
- Sensitive operations
- Missing information
- Low confidence
- Policy violations

---

# 40. Results Aggregator

Responsibilities

- Merge AgentResults
- Remove duplicates
- Build Shared Context
- Pass consolidated data to Risk Engine

Conflict Handling

If agents disagree:

- Prefer Policy Agent decisions.
- Record conflict in audit logs.
- Continue only if policy allows.

---

# 41. Retry Policy

Retry only recoverable failures.

| Error | Retry |
|--------|------|
| MCP Timeout | ✅ |
| Database Connection | ✅ |
| Vector Search Timeout | ✅ |
| Invalid Input | ❌ |
| Missing Customer | ❌ |

Retry Strategy

- Maximum: 3 attempts
- Exponential backoff
- Log every retry

---

# 42. Observability

Every workflow records:

- Workflow ID
- Node execution time
- LLM latency
- MCP tool calls
- Errors
- Retry count

Technologies

- OpenTelemetry
- Python Logging

---

# 43. Security

- JWT Authentication
- RBAC
- Input validation
- Environment variables via `.env`
- Parameterized SQL (SQLAlchemy)
- No secrets in source code

---

# 44. Deployment

Docker Services

```text
backend
postgres
redis
qdrant
enterprise-mcp
frontend
```

Start

```bash
docker compose up --build
```
All services must share a custom Docker bridge network. The Enterprise MCP Server must be accessible to the FastAPI backend via an internal hostname (e.g., http://enterprise-mcp:8000).

---

# 45. Testing

Unit Tests

- Agents
- Planner
- Risk Engine
- MCP Tools

Integration Tests

- Complete workflow
- Database
- RAG
- Approval flow

Target

- ≥80% code coverage

# 46. AI Coding Rules

These rules are mandatory for all generated code.

## Architecture

- Follow the folder structure defined in this SRS.
- Keep business logic out of FastAPI routes.
- LangGraph orchestrates the workflow.
- LLMs perform reasoning only.
- Task Planner is deterministic Python code.
- Agents never communicate directly with each other.

---

## State Management

- GraphState is the single source of truth.
- Every LangGraph node returns a state update dictionary.
- Never mutate GraphState in-place.
- Checkpoint after every node.
- Resume workflows only from checkpoints.

---

## Agents

Every agent must:

- Read only required state.
- Return a standard `AgentResult`.
- Be stateless.
- Use MCP tools when external data is required.
- Never execute SQL.
- Never execute HTTP requests.
- Never access environment variables directly.

---

## MCP

- Use one Enterprise MCP Server.
- Organize tools into namespaces.
- Execute all tools through LangGraph ToolNode.
- Never call MCP directly from FastAPI.
- Never bypass MCP.

---

## Database

- Use SQLAlchemy ORM.
- Parameterized queries only.
- UUID primary keys.
- Soft delete where applicable.
- Use transactions for write operations.

---

## RAG

- Retrieve before generation.
- Never generate unsupported facts.
- Return "insufficient information" when context is unavailable.
- Keep embedding model configurable.

---

## API

- Validate all requests with Pydantic.
- Return consistent HTTP status codes.
- Never expose internal exceptions.
- Use dependency injection where appropriate.

---

## Logging

Every node should log:

- workflow_id
- node_name
- execution_time
- tool_calls
- retry_count
- errors

---

## Error Handling

Recoverable

- Retry up to 3 times.
- Use exponential backoff.
- Log all retries.

Non-Recoverable

- Stop workflow.
- Persist audit log.
- Return failure status.

---

## Security

- JWT Authentication
- RBAC
- Secrets from `.env`
- Validate all user inputs
- Never log sensitive customer data

---

# 47. Project Structure

```text
agentflow-ai/
│
├── app/
│   ├── agents/
│   ├── graph/
│   ├── api/
│   ├── mcp/
│   ├── rag/
│   ├── database/
│   ├── models/
│   ├── services/
│   ├── prompts/
│   ├── observability/
│   ├── config/
│   └── utils/
│
├── frontend/
├── tests/
├── docker/
├── docs/
├── scripts/
│
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

# 48. Development Phases

### Phase 1

- Project setup
- PostgreSQL
- Redis
- FastAPI
- Docker

---

### Phase 2

- LangGraph
- GraphState
- Supervisor
- Task Planner

---

### Phase 3

- Enterprise MCP Server
- Billing tools
- Account tools
- Ticket tools
- Knowledge tools

---

### Phase 4

- Billing Agent
- Account Agent
- Technical Agent
- Policy Agent
- Response Agent

---

### Phase 5

- RAG
- Qdrant
- Knowledge ingestion

---

### Phase 6

- Results Aggregator
- Risk Engine
- HITL
- Workflow resume

---

### Phase 7

- Frontend Dashboard
- Workflow monitoring
- Approval interface

---

### Phase 8

- Testing
- Optimization
- Documentation

---

# 49. Acceptance Criteria

The project is complete when:

- Customer tickets create workflows successfully.
- Supervisor generates structured intent.
- Planner creates valid execution plans.
- Agents execute in parallel where possible.
- All enterprise operations use MCP.
- Knowledge retrieval works with Qdrant.
- Policy validation executes correctly.
- HITL pauses and resumes workflows.
- Response Agent generates final responses.
- Workflow state is recoverable.
- Complete audit logs are available.
- Docker Compose starts all services successfully.
- Unit and integration tests pass.

---

# 50. Future Enhancements

Potential improvements beyond Version 1.0:

- Multi-tenant architecture
- Real Stripe integration
- Zendesk integration
- Salesforce integration
- Slack notifications
- Email automation
- Kubernetes deployment
- Multi-language support
- Voice support
- Multi-modal document ingestion
- Agent performance analytics
- Automatic workflow optimisation

---

# 51. References

### Frameworks

- FastAPI
- LangGraph
- Model Context Protocol (MCP)
- SQLAlchemy
- Qdrant
- Redis
- PostgreSQL
- Docker
- React
- OpenTelemetry

---

# End of Software Requirements Specification