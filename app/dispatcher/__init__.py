"""Queue dispatcher: consumes workflow jobs from Redis and runs the graph.

This package is the only place a LangGraph workflow is actually executed.
FastAPI queues jobs and returns 202 (SRS §36); the dispatcher process picks them
up, runs the graph against the Postgres checkpointer, and persists the outcome.
"""

from app.dispatcher.consumer import WorkflowConsumer
from app.dispatcher.runner import WorkflowRunner

__all__ = ["WorkflowConsumer", "WorkflowRunner"]
