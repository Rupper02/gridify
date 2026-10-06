"""What the domain layers (the repository, projects, jobs, the service) refuse with, free of HTTP: the agents' tools
and the workflows read them as plain errors, and `main.py` maps each kind to its status code once."""

from __future__ import annotations


class DomainError(Exception):
    """A refusal the caller can act on. `detail` is what the API answers: a sentence, or a dict with a `message`."""

    def __init__(self, detail: str | dict):
        self.detail = detail
        super().__init__(detail["message"] if isinstance(detail, dict) else detail)


class NotFound(DomainError):
    """No such branch, project or job."""


class Gone(DomainError):
    """It existed, but what it needs is no longer there (an imported project's file)."""


class Conflict(DomainError):
    """Not in this state: a main is read-only, a branch is not open, the built-in project stays."""


class Invalid(DomainError):
    """The request is understood but cannot be planned on (an unreadable or incomplete grid, an unknown pathway)."""


class UnsupportedFile(DomainError):
    """A file type no importer reads."""


class TooLarge(DomainError):
    """Over the import size limit."""


STATUS: dict[type[DomainError], int] = {NotFound: 404, Gone: 410, Conflict: 409, Invalid: 422, UnsupportedFile: 415, TooLarge: 413}


def status_of(exc: DomainError) -> int:
    """The status of a refusal by its kind, a subclass answering as its kind (repository.UnknownElement is Invalid)."""
    return next((STATUS[k] for k in type(exc).__mro__ if k in STATUS), 400)
