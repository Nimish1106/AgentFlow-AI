"""Workflow status queries (kept out of routes)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentExecutionLog, WorkflowRun
from app.services.exceptions import WorkflowNotFoundError


class WorkflowService:
    """Reads workflow run state and completed-agent history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_workflow_status(
        self, workflow_id: uuid.UUID
    ) -> tuple[WorkflowRun, list[str]]:
        """Return a workflow run and the names of agents that completed."""
        workflow = await self._session.get(WorkflowRun, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(str(workflow_id))

        completed_agents = list(
            await self._session.scalars(
                select(AgentExecutionLog.agent_name)
                .where(
                    AgentExecutionLog.workflow_id == workflow_id,
                    AgentExecutionLog.status == "completed",
                )
                .order_by(AgentExecutionLog.created_at)
            )
        )
        return workflow, completed_agents
