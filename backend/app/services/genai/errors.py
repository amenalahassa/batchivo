"""Domain errors of the generative AI layer (spec 008, research R1).

The service raises these, never ``HTTPException``, so that it can be called
outside a request (scripts, Preflight, the MCP server of feature 010). The
routers map them to HTTP with ``detail = {"code", "message"}``.
"""

from typing import Optional


class GenAIError(Exception):
    """A refusal or failure with a stable code that callers can branch on."""

    code: str = "genai_error"
    http_status: int = 400

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def detail(self) -> dict:
        """The body a router returns for this error."""
        return {"code": self.code, "message": self.message}


class NotConnected(GenAIError):
    """No usable provider token for this tenant."""

    code = "not_connected"
    http_status = 409


class BudgetExceeded(GenAIError):
    """The job would take the month's spend over the tenant's budget."""

    code = "budget_exceeded"
    http_status = 409


class ConcurrencyLimit(GenAIError):
    """The tenant already runs the maximum number of jobs."""

    code = "concurrency_limit"
    http_status = 409


class NotCancellable(GenAIError):
    """The job is already finished."""

    code = "not_cancellable"
    http_status = 409


class AlreadyAdopted(GenAIError):
    """The output was already adopted into this target."""

    code = "already_adopted"
    http_status = 409


class NeedsConfirmation(GenAIError):
    """Adopting this output as a product image needs the operator's confirmation."""

    code = "needs_confirmation"
    http_status = 409


class NotSucceeded(GenAIError):
    """The output's job has not succeeded."""

    code = "not_succeeded"
    http_status = 409


class WrongKind(GenAIError):
    """An image where a mesh is needed, or the reverse."""

    code = "wrong_kind"
    http_status = 422


class InputInvalid(GenAIError):
    """Inputs that fail the capability's rules."""

    code = "input_invalid"
    http_status = 422


class NotFound(GenAIError):
    """A job, asset or target that does not exist in this tenant."""

    code = "not_found"
    http_status = 404


class QueueUnavailable(GenAIError):
    """The job could not be handed to a worker."""

    code = "queue_unavailable"
    http_status = 503


__all__ = [
    "AlreadyAdopted",
    "BudgetExceeded",
    "ConcurrencyLimit",
    "GenAIError",
    "InputInvalid",
    "NeedsConfirmation",
    "NotCancellable",
    "NotConnected",
    "NotFound",
    "NotSucceeded",
    "QueueUnavailable",
    "WrongKind",
]
