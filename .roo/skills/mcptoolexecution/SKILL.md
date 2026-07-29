---
name: mcptoolexecution
description: Use this whenever writing agent reasoning loops or tool execution logic.
---

# Mcptoolexecution

## Instructions

When implementing agent tool logic:
1. Agents do NOT execute tools directly. They must use `.bind_tools()` to generate a `tool_call`.
2. A dedicated LangGraph `ToolNode` must be used to intercept the `tool_call` and route it to the Enterprise MCP Server.
3. Use strictly namespaced tool names (e.g., `billing_get_invoice`, `knowledge_semantic_search`).