---
name: langgraphstaterules
description: Use this whenever generating LangGraph node functions or state definitions.
---

# Langgraphstaterules

## Instructions

When writing LangGraph code for this project:
1. Always use `Annotated[List[AgentResult], operator.add]` for lists in the GraphState to prevent parallel execution overwrites.
2. Node functions must return a dictionary representing the state update (e.g., `return {"agent_results": [result]}`).
3. Never mutate the GraphState in-place.
4. Ensure `thread_id` (mapped to `workflow_id`) is passed into the `RunnableConfig` for checkpointing.
