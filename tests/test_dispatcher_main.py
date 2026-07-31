"""Tests for the dispatcher process entrypoint wiring (``app.dispatcher.main``)."""

import asyncio
import contextlib
import signal

import pytest

import app.dispatcher.main as dispatcher_main


class FakeRedisClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeConsumer:
    """Consumer stand-in that records construction and exits immediately."""

    instances: list["FakeConsumer"] = []

    def __init__(self, client, runner, **kwargs) -> None:
        self.client = client
        self.runner = runner
        self.ran = False
        self.stopped = False
        FakeConsumer.instances.append(self)

    async def run_forever(self) -> None:
        self.ran = True

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def wired(monkeypatch):
    """Patch every external dependency of ``run_dispatcher``."""
    FakeConsumer.instances.clear()
    client = FakeRedisClient()
    built = {}

    @contextlib.asynccontextmanager
    async def fake_checkpointer_context():
        built["checkpointer_entered"] = True
        yield "checkpointer-sentinel"
        built["checkpointer_exited"] = True

    def fake_build_graph(*, checkpointer=None, **kwargs):
        built["checkpointer"] = checkpointer
        return "graph-sentinel"

    class FakeRedisModule:
        class Redis:
            @staticmethod
            def from_url(url, decode_responses=True, **kwargs):
                built["redis_url"] = url
                built["redis_kwargs"] = kwargs
                return client

    async def fake_dispose():
        built["engine_disposed"] = True

    class FakeEngine:
        dispose = staticmethod(fake_dispose)

    monkeypatch.setattr(dispatcher_main, "redis", FakeRedisModule)
    monkeypatch.setattr(
        dispatcher_main, "checkpointer_context", fake_checkpointer_context
    )
    monkeypatch.setattr(dispatcher_main, "build_workflow_graph", fake_build_graph)
    monkeypatch.setattr(dispatcher_main, "WorkflowConsumer", FakeConsumer)
    monkeypatch.setattr(dispatcher_main, "configure_logging", lambda: None)
    # AsyncEngine.dispose is read-only, so swap the whole engine reference.
    monkeypatch.setattr(dispatcher_main, "engine", FakeEngine)
    return built, client


class TestRunDispatcher:
    async def test_compiles_the_graph_against_the_postgres_checkpointer(self, wired):
        """A graph compiled without the saver could not resume an interrupt."""
        built, _ = wired
        await dispatcher_main.run_dispatcher()
        assert built["checkpointer_entered"] is True
        assert built["checkpointer"] == "checkpointer-sentinel"

    async def test_consumes_the_queue(self, wired):
        await dispatcher_main.run_dispatcher()
        assert FakeConsumer.instances[0].ran is True

    async def test_runner_receives_the_compiled_graph(self, wired):
        await dispatcher_main.run_dispatcher()
        assert FakeConsumer.instances[0].runner._graph == "graph-sentinel"

    async def test_releases_redis_and_the_engine_on_exit(self, wired):
        built, client = wired
        await dispatcher_main.run_dispatcher()
        assert client.closed is True
        assert built["engine_disposed"] is True

    async def test_releases_connections_even_when_consuming_fails(
        self, wired, monkeypatch
    ):
        built, client = wired

        async def failing_run_forever(self):
            raise RuntimeError("redis went away")

        monkeypatch.setattr(FakeConsumer, "run_forever", failing_run_forever)

        with pytest.raises(RuntimeError, match="redis went away"):
            await dispatcher_main.run_dispatcher()

        assert client.closed is True
        assert built["engine_disposed"] is True


class TestRedisClient:
    def test_socket_timeout_outlives_the_blocking_read(self, monkeypatch):
        """redis-py defaults socket_timeout to 5s - exactly the block window.

        Without headroom the socket read deadline expires on every idle poll and
        the consume loop logs a spurious TimeoutError (observed live).
        """
        from app.config.settings import Settings

        captured = {}

        class FakeRedisModule:
            class Redis:
                @staticmethod
                def from_url(url, **kwargs):
                    captured.update(kwargs)
                    return object()

        monkeypatch.setattr(dispatcher_main, "redis", FakeRedisModule)
        monkeypatch.setattr(
            dispatcher_main,
            "get_settings",
            lambda: Settings(dispatcher_block_ms=5000),
        )

        dispatcher_main.build_redis_client()

        assert captured["socket_timeout"] > 5.0
        assert captured["decode_responses"] is True


class TestSignalHandlers:
    async def test_sigterm_stops_the_consumer(self):
        """Compose sends SIGTERM on `docker compose down`."""
        consumer = FakeConsumer(None, None)
        loop = asyncio.get_running_loop()
        registered = {}

        def fake_add_signal_handler(sig, callback):
            registered[sig] = callback

        original = loop.add_signal_handler
        loop.add_signal_handler = fake_add_signal_handler
        try:
            dispatcher_main._install_signal_handlers(consumer)
        finally:
            loop.add_signal_handler = original

        assert signal.SIGTERM in registered
        registered[signal.SIGTERM]()
        assert consumer.stopped is True

    async def test_unsupported_signals_are_not_fatal(self):
        """Windows does not implement add_signal_handler at all."""
        consumer = FakeConsumer(None, None)
        loop = asyncio.get_running_loop()

        def unsupported(sig, callback):
            raise NotImplementedError

        original = loop.add_signal_handler
        loop.add_signal_handler = unsupported
        try:
            dispatcher_main._install_signal_handlers(consumer)  # must not raise
        finally:
            loop.add_signal_handler = original
