"""What the agents must answer with: typed outputs the server validates and binds to evidence.

An agent never types a figure into these. A finding names a recorded step and an item; a review
restates the gate's blockers by fingerprint; the server copies the numbers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .evidence import AgentFinding

__all__ = ["AgentFinding", "HealthBrief", "Restated", "ReviewComment", "SpecialistReport", "SpecialistRequest", "StewardPlan"]

MAX_NOT_STUDIED = 3  # what a model may list as not studied; the harness adds the studies in remit it did not run
MAX_NEXT_CHECKS = 5

_NOT_STUDIED = Field(default=[], description="at most three things the question or the event raised that no study you ran "
                                              "answers (the harness adds the studies in your remit you did not run)")


def _capped(n: int):
    """A list field the model writes, kept to its first `n` items rather than sent back (a long list is noise, not an error)."""
    def cap(cls, v):  # noqa: ANN001
        return list(v or [])[:n]
    return cap


class SpecialistRequest(BaseModel):
    """One specialist the steward asks for, and why."""

    kind: str = Field(description="the specialist's name, from the allowed list")
    branch_id: str | None = Field(default=None, description="the branch to study; null = the project's main")
    why: str = Field(description="one sentence: what in the event or the findings calls for this study")


class StewardPlan(BaseModel):
    """The steward's triage of an event: which specialists to run (possibly none)."""

    specialists: list[SpecialistRequest] = []
    note: str = Field(default="", description="one sentence on what the event changes, or why nothing needs studying")


class SpecialistReport(BaseModel):
    """A specialist's findings: each one points at an item of a study it ran (step id + item index)
    and adds only words; the server copies the figures from the step."""

    findings: list[AgentFinding] = []
    not_studied: list[str] = _NOT_STUDIED
    summary: str = Field(description="two or three plain sentences; every figure quoted as a tool gave it")

    _cap_not_studied = field_validator("not_studied")(classmethod(_capped(MAX_NOT_STUDIED)))


class Restated(BaseModel):
    """One gate item, restated: identified by its kind and element as the gate gave them (an item stands for one
    problem on one element across the plan years it applies to), with the ledger fingerprint the gate carries
    (the UI's evidence link)."""

    kind: str = Field(description="the gate finding's kind, copied exactly")
    element_id: str | None = Field(default=None, description="the gate finding's element_id, copied exactly (null when it has none)")
    fingerprint: str | None = Field(default=None, description="the gate finding's fingerprint, copied exactly, or null when it has none")
    restated: str = Field(description="the finding in one plain sentence, figures as the gate gave them")


class ReviewComment(BaseModel):
    """The reviewer's comment on a branch run: the gate's verdict restated, nothing added."""

    verdict_restated: Literal["blocked", "mergeable_with_warnings", "mergeable"]
    blockers: list[Restated] = []
    warnings: list[Restated] = []
    body: str = Field(description="at most 150 words for the engineer: what the branch does, what blocks or warns, what to check next")
    not_studied: list[str] = _NOT_STUDIED

    _cap_not_studied = field_validator("not_studied")(classmethod(_capped(MAX_NOT_STUDIED)))


class HealthBrief(BaseModel):
    """The steward's brief after its specialists report: the state of the project in words."""

    headline: str = Field(description="one sentence")
    body: str = Field(description="at most 200 words; every figure as a specialist or tool gave it, cited as [step <id>]")
    not_studied: list[str] = _NOT_STUDIED
    next_checks: list[str] = Field(default=[], description="at most five things an engineer should look at next, each a short question "
                                                            "the agents could be asked (the planner offers them as questions)")

    _cap_not_studied = field_validator("not_studied")(classmethod(_capped(MAX_NOT_STUDIED)))
    _cap_next_checks = field_validator("next_checks")(classmethod(_capped(MAX_NEXT_CHECKS)))
