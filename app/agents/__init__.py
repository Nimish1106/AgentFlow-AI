"""Domain agents for the AgentFlow workflow (SRS §30).

Every agent here follows the same discipline: read GraphState, reason with an
LLM, reach the outside world only through MCP tool_calls executed by a
LangGraph ToolNode, and return a state-update dict carrying the uniform
``AgentResult`` contract.
"""
