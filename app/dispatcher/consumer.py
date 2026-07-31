"""Redis Streams consumer that feeds the workflow runner (SRS §14, §19).

``POST /tickets`` returns 202 immediately and only queues a job; this consumer is
what finally executes the graph. It reads the workflow stream through a consumer
group, so several dispatcher replicas can share the load and an unacknowledged
job is redelivered after a crash (SRS §16.6: every failure must be recoverable).

Acknowledgement policy: a job is ACKed once its outcome has been persisted -
including a *failed* outcome. Leaving a poison job unacknowledged would have the
group redeliver it forever; the failure is already recorded in
``workflow_runs`` + ``audit_logs``, so retrying it blindly adds nothing.
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Tuple

import redis.asyncio as redis
from redis.exceptions import ResponseError

from app.config.settings import get_settings
from app.dispatcher.runner import WorkflowRunner
from app.services.queue_service import KIND_RESUME, KIND_START, parse_decision

logger = logging.getLogger(__name__)


class WorkflowConsumer:
    """Consumes workflow jobs from the Redis Stream and runs them."""

    def __init__(
        self,
        client: redis.Redis,
        runner: WorkflowRunner,
        *,
        stream: Optional[str] = None,
        group: Optional[str] = None,
        consumer_name: Optional[str] = None,
        block_ms: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._client = client
        self._runner = runner
        self._stream = stream or settings.workflow_stream
        self._group = group or settings.dispatcher_consumer_group
        self._consumer = consumer_name or settings.dispatcher_consumer_name
        self._block_ms = block_ms if block_ms is not None else settings.dispatcher_block_ms
        self._running = False

    async def ensure_group(self) -> None:
        """Create the consumer group, tolerating an existing one.

        ``mkstream=True`` creates the stream too, so the dispatcher can boot
        before the first ticket is ever submitted.
        """
        try:
            await self._client.xgroup_create(
                self._stream, self._group, id="0", mkstream=True
            )
            logger.info(
                "created consumer group=%s on stream=%s", self._group, self._stream
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
            logger.debug("consumer group=%s already exists", self._group)

    async def run_forever(self) -> None:
        """Read and process jobs until :meth:`stop` is called."""
        await self.ensure_group()
        self._running = True
        logger.info(
            "dispatcher consuming stream=%s group=%s consumer=%s",
            self._stream,
            self._group,
            self._consumer,
        )
        while self._running:
            try:
                processed = await self.process_batch()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive one bad batch
                logger.exception("dispatcher batch failed; continuing")
                # Back off briefly so a persistent fault does not spin the CPU.
                await asyncio.sleep(1)
                continue
            if not processed:
                continue

    def stop(self) -> None:
        """Ask the consume loop to exit after the current batch."""
        self._running = False

    async def process_batch(self, count: int = 1) -> int:
        """Read up to ``count`` jobs, process them, and return how many ran."""
        entries = await self._read(count)
        processed = 0
        for entry_id, fields in entries:
            await self._handle_entry(entry_id, fields)
            processed += 1
        return processed

    async def _read(self, count: int) -> List[Tuple[str, Dict]]:
        """Read new jobs for this consumer, returning (entry_id, fields) pairs."""
        response = await self._client.xreadgroup(
            self._group,
            self._consumer,
            {self._stream: ">"},
            count=count,
            block=self._block_ms,
        )
        if not response:
            return []
        entries: List[Tuple[str, Dict]] = []
        for _stream_name, stream_entries in response:
            entries.extend(stream_entries)
        return entries

    async def _handle_entry(self, entry_id: str, fields: Dict) -> None:
        """Dispatch one job by kind, then acknowledge it."""
        workflow_id_raw = fields.get("workflow_id", "")
        kind = fields.get("kind", KIND_START)
        try:
            workflow_id = uuid.UUID(workflow_id_raw)
        except (ValueError, AttributeError, TypeError):
            logger.error(
                "entry=%s has unusable workflow_id=%r; acknowledging",
                entry_id,
                workflow_id_raw,
            )
            await self._ack(entry_id)
            return

        try:
            if kind == KIND_RESUME:
                decision = parse_decision(fields)
                if decision is None:
                    logger.error(
                        "workflow_id=%s resume job carries no decision; skipping",
                        workflow_id,
                    )
                else:
                    await self._runner.resume(workflow_id, decision)
            else:
                await self._runner.run(workflow_id)
        except Exception:  # noqa: BLE001 - outcome is already persisted as failed
            logger.exception(
                "workflow_id=%s kind=%s job failed", workflow_id, kind
            )
        finally:
            await self._ack(entry_id)

    async def _ack(self, entry_id: str) -> None:
        """Acknowledge one stream entry."""
        try:
            await self._client.xack(self._stream, self._group, entry_id)
        except Exception:  # noqa: BLE001 - a failed ack must not kill the loop
            logger.exception("entry=%s acknowledgement failed", entry_id)
