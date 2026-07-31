"""Domain exceptions raised by services and translated to HTTP errors in routes."""


class NotFoundError(Exception):
    """Base class for missing-entity errors (non-recoverable, SRS §35)."""


class CustomerNotFoundError(NotFoundError):
    """The referenced customer does not exist."""


class TicketNotFoundError(NotFoundError):
    """The referenced support ticket does not exist."""


class WorkflowNotFoundError(NotFoundError):
    """The referenced workflow run does not exist."""


class InvoiceNotFoundError(NotFoundError):
    """The referenced invoice does not exist."""


class WorkflowNotAwaitingApprovalError(Exception):
    """The workflow is not parked at the HITL interrupt (SRS §38).

    Approving a workflow that never asked for approval - or approving one twice -
    is a client error, not a missing entity: the workflow exists, its state just
    does not permit the transition.
    """

    def __init__(self, workflow_id: str, workflow_status: str) -> None:
        super().__init__(
            f"workflow {workflow_id} is {workflow_status}, not waiting_for_hitl"
        )
        self.workflow_id = workflow_id
        self.workflow_status = workflow_status


class SubscriptionNotFoundError(NotFoundError):
    """No subscription exists for the referenced customer."""
