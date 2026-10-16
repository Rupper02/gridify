"""What the domain layers (the repository, the grid, jobs, the service) refuse with, free of HTTP: `main.py` maps each
kind to its status code once."""

from __future__ import annotations


class DomainError(Exception):
    """A refusal the caller can act on. `detail` is what the API answers: a sentence, or a dict with a `message`."""

    def __init__(self, detail: str | dict):
        self.detail = detail
        super().__init__(detail["message"] if isinstance(detail, dict) else detail)


class NotFound(DomainError):
    """No such branch, connection or job."""


class Conflict(DomainError):
    """Not in this state: main is read-only, a branch is not open."""


class NotSolved(Conflict):
    """Not computed yet, and this read does not compute it: run the branch first (`retry: false`), or the engine is
    busy with a run and the read is worth asking again when it finishes (`retry: true`)."""

    def __init__(self, message: str, *, retry: bool):
        super().__init__({"code": "not_solved", "message": message, "retry": retry})


class Invalid(DomainError):
    """The request is understood but cannot be simulated (a bus not in the model, a year outside the plan)."""


STATUS: dict[type[DomainError], int] = {NotFound: 404, Conflict: 409, Invalid: 422}


def status_of(exc: DomainError) -> int:
    """The status of a refusal by its kind, a subclass answering as its kind."""
    return next((STATUS[k] for k in type(exc).__mro__ if k in STATUS), 400)
