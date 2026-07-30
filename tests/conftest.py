"""Shared test fixtures: in-memory SQLite DB, fake Redis client, fake LLM."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (populate Base.metadata)
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
