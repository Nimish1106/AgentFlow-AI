"""Shared test fixtures: in-memory SQLite DB, fake Redis client, fake LLM."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (populate Base.metadata)
import app.mcp.server.runtime as mcp_runtime
from app.database.base import Base
from app.database.redis import get_redis
from app.database.session import get_db
from app.main import app


class FakeRedis:
    """Minimal async Redis stand-in recording stream entries."""

    def __init__(self) -> None:
        self.streams: dict[str, list[dict]] = {}

    async def xadd(self, stream: str, fields: dict) -> str:
        self.streams.setdefault(stream, []).append(fields)
        return f"{len(self.streams[stream])}-0"

    async def ping(self) -> bool:
        return True


class FakeStructuredLLM:
    """Chat-model stand-in for nodes that use ``with_structured_output``.

    Only the surface the Supervisor touches is implemented: ``with_structured_output``
    returning something awaitable via ``ainvoke``. Set ``raises`` to simulate an
    LLM failure.
    """

    def __init__(self, result=None, raises: Exception | None = None) -> None:
        self.result = result
        self.raises = raises
        self.calls: list = []

    def with_structured_output(self, schema, **kwargs):  # noqa: ARG002
        self.schema = schema
        return self

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        self.calls.append(messages)
        if self.raises is not None:
            raise self.raises
        return self.result


@pytest.fixture
def fake_llm_factory():
    """Return a builder for FakeStructuredLLM instances."""
    return FakeStructuredLLM


class FakeAgentLLM:
    """Chat-model stand-in for agents that bind tools and emit structured output.

    ``tool_call_batches`` scripts the tool loop: each ``ainvoke`` on the bound
    model pops one batch and returns an AIMessage carrying those tool_calls;
    when the queue is empty it returns a plain AIMessage, ending the loop.

    ``outcomes`` maps schema class -> instance, so one fake can serve every
    reasoning node in a full-graph run (Supervisor, domain agents, Policy,
    Response), each requesting its own schema.
    """

    def __init__(
        self,
        outcomes: dict | None = None,
        tool_call_batches: list[list[dict]] | None = None,
    ) -> None:
        self.outcomes = outcomes or {}
        self.tool_call_batches = list(tool_call_batches or [])
        self.bound_tools: list = []
        self.structured_calls: list = []

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002
        self.bound_tools.append(list(tools))
        return _FakeBoundModel(self)

    def with_structured_output(self, schema, **kwargs):  # noqa: ARG002
        return _FakeStructuredModel(self, schema)


class _FakeBoundModel:
    def __init__(self, parent: FakeAgentLLM) -> None:
        self._parent = parent

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        if self._parent.tool_call_batches:
            batch = self._parent.tool_call_batches.pop(0)
            return AIMessage(content="", tool_calls=batch)
        return AIMessage(content="done")


class _FakeStructuredModel:
    def __init__(self, parent: FakeAgentLLM, schema) -> None:
        self._parent = parent
        self._schema = schema

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        self._parent.structured_calls.append((self._schema, messages))
        try:
            return self._parent.outcomes[self._schema]
        except KeyError as exc:
            raise AssertionError(
                f"no scripted outcome for schema {self._schema!r}"
            ) from exc


@pytest.fixture
def fake_agent_llm_factory():
    """Return a builder for FakeAgentLLM instances."""
    return FakeAgentLLM


class FakeMCPClient:
    """EnterpriseMCPClient stand-in returning scripted tool payloads.

    ``responses`` maps tool name -> dict payload, callable, or list of
    payloads consumed one per call (to script retry sequences). Unknown tools
    return a structured not_found error, mirroring the real server's
    exceptions-never-cross-the-boundary contract.
    """

    def __init__(self, responses: dict | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[str]:
        return list(self.responses)

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        response = self.responses.get(
            name, {"error": f"unknown tool {name}", "code": "not_found"}
        )
        if isinstance(response, list):
            response = response.pop(0) if len(response) > 1 else response[0]
        if callable(response):
            response = response(arguments)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def fake_mcp_client_factory():
    """Return a builder for FakeMCPClient instances."""
    return FakeMCPClient


class FakeRetriever:
    """KnowledgeRetriever stand-in returning scripted RetrievedChunk hits."""

    def __init__(self, hits: list | None = None) -> None:
        self.hits = list(hits or [])
        self.calls: list[dict] = []

    async def search(self, query, *, top_k=None, doc_types=None):
        self.calls.append({"query": query, "top_k": top_k, "doc_types": doc_types})
        return list(self.hits)


@pytest.fixture
def fake_retriever_factory():
    """Return a builder for FakeRetriever instances."""
    return FakeRetriever


@pytest_asyncio.fixture
async def db_engine():
    """Fresh in-memory SQLite database per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    """Session factory bound to the test database."""
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def fake_redis():
    """Fake Redis shared between the app under test and assertions."""
    return FakeRedis()


@pytest_asyncio.fixture
async def mcp_session_factory(session_factory):
    """Point the MCP runtime at the test database; restore afterwards."""
    mcp_runtime.set_session_factory(session_factory)
    yield session_factory
    mcp_runtime._session_factory = None


@pytest_asyncio.fixture
async def client(session_factory, fake_redis):
    """HTTP client against the app with DB and Redis dependencies overridden."""

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_redis():
        yield fake_redis

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = override_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()
