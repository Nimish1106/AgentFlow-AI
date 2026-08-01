"""Enterprise MCP Server entry point (SRS §31, §44).

One FastMCP server exposing all four tool namespaces over streamable-http.
Run with: ``uvicorn app.mcp.server.main:app --host 0.0.0.0 --port 8000``.
"""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.mcp.server.tools import account, billing, knowledge, ticket
from app.observability.logging import configure_logging
from app.observability.tracing import configure_tracing


def create_mcp_server() -> FastMCP:
    """Build the Enterprise MCP server with every tool namespace registered."""
    mcp = FastMCP(
        "enterprise",
        instructions=(
            "Enterprise MCP Server for AgentFlow AI. Exposes billing, account, "
            "ticket, and knowledge tools. All tool calls are audited."
        ),
        stateless_http=True,
        # The server is reached over the internal Docker network by service
        # name (http://enterprise-mcp:8000). DNS-rebinding protection rejects
        # those Host headers unless they are explicitly allowed.
        transport_security=TransportSecuritySettings(
            allowed_hosts=["enterprise-mcp:8000", "localhost:8000", "127.0.0.1:8000"],
            allowed_origins=[
                "http://enterprise-mcp:8000",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            ],
        ),
    )
    billing.register(mcp)
    account.register(mcp)
    ticket.register(mcp)
    knowledge.register(mcp)
    return mcp


configure_logging()
# Tool-call spans (SRS §42); a no-op unless OTEL_ENABLED is set.
configure_tracing()
mcp_server = create_mcp_server()
app = mcp_server.streamable_http_app()
