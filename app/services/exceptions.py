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


class SubscriptionNotFoundError(NotFoundError):
    """No subscription exists for the referenced customer."""
