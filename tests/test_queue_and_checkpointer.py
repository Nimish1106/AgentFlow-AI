"""Tests for the queue job envelope and the Postgres checkpointer wiring."""

import json
import uuid

import pytest

from app.graph.checkpointer import to_psycopg_dsn
from app.services.queue_service import (
    KIND_RESUME,
    KIND_START,
    QueueService,
    parse_decision,
)


class TestQueueService:
    async def test_start_job_carries_the_workflow_and_ticket(self, fake_redis):
        workflow_id, ticket_id = uuid.uuid4(), uuid.uuid4()

        await QueueService(fake_redis).enqueue_workflow(workflow_id, ticket_id)

        [job] = [j for entries in fake_redis.streams.values() for j in entries]
        assert job["kind"] == KIND_START
        assert job["workflow_id"] == str(workflow_id)
        assert job["ticket_id"] == str(ticket_id)

    async def test_resume_job_carries_the_reviewer_decision(self, fake_redis):
        workflow_id, ticket_id = uuid.uuid4(), uuid.uuid4()

        await QueueService(fake_redis).enqueue_resume(
            workflow_id,
            ticket_id,
            approved=False,
            reviewer_name="Support Manager",
            comments="Needs sign-off.",
        )

        [job] = [j for entries in fake_redis.streams.values() for j in entries]
        assert job["kind"] == KIND_RESUME
        assert json.loads(job["decision"]) == {
            "approved": False,
            "reviewer_name": "Support Manager",
            "comments": "Needs sign-off.",
        }

    async def test_both_kinds_share_one_stream(self, fake_redis):
        """Ordering per workflow depends on a single stream."""
        queue = QueueService(fake_redis)
        workflow_id, ticket_id = uuid.uuid4(), uuid.uuid4()

        await queue.enqueue_workflow(workflow_id, ticket_id)
        await queue.enqueue_resume(
            workflow_id, ticket_id, approved=True, reviewer_name="Manager"
        )

        assert len(fake_redis.streams) == 1
        assert len(next(iter(fake_redis.streams.values()))) == 2


class TestDecisionEnvelopeParsing:
    def test_reads_a_well_formed_decision(self):
        fields = {"decision": json.dumps({"approved": True, "reviewer_name": "M"})}
        assert parse_decision(fields)["approved"] is True

    @pytest.mark.parametrize(
        "fields",
        [
            {},  # no decision at all
            {"decision": ""},  # empty
            {"decision": "not json"},  # unparseable
            {"decision": json.dumps({"reviewer_name": "M"})},  # no verdict
            {"decision": json.dumps(["approved"])},  # wrong shape
        ],
    )
    def test_unusable_envelopes_yield_none(self, fields):
        """The dispatcher must skip rather than guess a verdict."""
        assert parse_decision(fields) is None


class TestCheckpointerDsn:
    def test_strips_the_asyncpg_driver(self):
        """AsyncPostgresSaver uses psycopg, not the app's asyncpg engine."""
        assert (
            to_psycopg_dsn("postgresql+asyncpg://user:pw@postgres:5432/agentflow")
            == "postgresql://user:pw@postgres:5432/agentflow"
        )

    def test_strips_the_psycopg_driver(self):
        assert (
            to_psycopg_dsn("postgresql+psycopg://user:pw@host:5432/db")
            == "postgresql://user:pw@host:5432/db"
        )

    def test_leaves_a_plain_dsn_untouched(self):
        dsn = "postgresql://user:pw@host:5432/db"
        assert to_psycopg_dsn(dsn) == dsn
