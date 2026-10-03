"""The roster: which agents exist, what each may do, and how they are built.

Every agent is one `AgentSpec` (a registry entry): its model role, its instructions, the tool groups
it gets, its typed output and its run budget. `build` turns the roster into Pydantic AI agents with the
DBOS durability capability and the server-side validators that keep figures honest.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from pydantic_ai import Agent, DeferredToolRequests, ModelRetry, RunContext
from pydantic_ai.durable_exec.dbos import DBOSDurability
from pydantic_ai.models import Model

from . import prompts
from .schemas import HealthBrief, ReviewComment, SpecialistReport, StewardPlan
from .streaming import on_event
from .tools import TOOL_GROUPS, AgentDeps

# which studies each specialist may run (its remit; the tools refuse the rest)
SPECIALIST_STUDIES: dict[str, tuple[str, ...]] = {
    "thermal": ("hosting_capacity", "contingency_ranking"),
    "voltage": ("tap_margin", "hosting_capacity"),
    "demand_security": ("contingency_ranking", "structural_weak_points"),
    "boundary": ("gsp_margin_by_year",),
    "data_quality": ("data_quality",),
    "works": ("contingency_ranking",),
}


class AgentSpec(NamedTuple):
    role: str  # the model role (config.AGENT_MODELS)
    instructions: str
    tools: tuple[str, ...]  # TOOL_GROUPS keys
    output_type: Any
    studies: tuple[str, ...] = ()  # the studies its tools may run ("studies" group)


AGENTS: dict[str, AgentSpec] = {
    "steward": AgentSpec("steward", prompts.STEWARD_TRIAGE, ("read",), StewardPlan),
    "steward_brief": AgentSpec("steward", prompts.STEWARD_BRIEF, ("read",), HealthBrief),
    **{kind: AgentSpec("specialist", prompts.specialist_prompt(kind), ("read", "studies"), SpecialistReport, SPECIALIST_STUDIES[kind])
       for kind in SPECIALIST_STUDIES},
    "reviewer": AgentSpec("reviewer", prompts.REVIEWER, ("read", "studies"), ReviewComment, ("contingency_ranking",)),
    "answerer": AgentSpec("answerer", prompts.ANSWERER, ("read", "studies", "proposals"), [str, DeferredToolRequests], tuple(SPECIALIST_STUDIES["thermal"] + SPECIALIST_STUDIES["voltage"] + SPECIALIST_STUDIES["demand_security"] + SPECIALIST_STUDIES["boundary"] + SPECIALIST_STUDIES["data_quality"])),
}
SPECIALISTS: tuple[str, ...] = tuple(SPECIALIST_STUDIES)


# --- the validators that keep figures honest ---------------------------------------------------------------
def _validate_report(ctx: RunContext[AgentDeps], report: SpecialistReport) -> SpecialistReport:
    """Every finding must name a study step of THIS run and an item it has (the server copies the figures)."""
    bad = []
    for f in report.findings:
        step = ctx.deps.h.evidence.load_step(f.step_id)
        if step is None or step.run_id != ctx.deps.run_id or step.study is None:
            bad.append(f"{f.step_id} is not a study step of this run")
        elif not (0 <= f.item_index < len(step.study.items)):
            bad.append(f"{f.step_id} has no item {f.item_index} (it has {len(step.study.items)})")
    if bad:
        raise ModelRetry("Some findings do not point at a recorded study item: " + "; ".join(bad) + ". Use the step_id and item index a study tool returned in this run.")
    return report


def _identity(f: dict) -> tuple:
    return (f.get("kind"), None if f.get("element_id") is None else str(f["element_id"]), f.get("fingerprint") or None)


def _validate_review(ctx: RunContext[AgentDeps], review: ReviewComment) -> ReviewComment:
    """The reviewer restates the gate, nothing more and nothing less: every blocker it lists must be one
    the merge check produced (same kind, element and fingerprint) and every gate blocker must be there."""
    gate = ctx.deps.context.get("merge_check") or {}
    want = {_identity(f) for f in gate.get("blockers", [])}
    got = {_identity(b.model_dump()) for b in review.blockers}
    unknown = got - want
    missing = want - got
    if unknown or missing:
        raise ModelRetry("Restate exactly the gate's blockers, each with its kind, element_id and fingerprint copied from the gate. "
                         + (f"Not from the gate: {sorted(map(str, unknown))}. " if unknown else "")
                         + (f"Missing: {sorted(map(str, missing))}. " if missing else "")
                         + f"The gate's blockers are: {gate.get('blockers', [])}")
    expected = "blocked" if gate.get("blockers") else ("mergeable_with_warnings" if gate.get("warnings") else "mergeable")
    if review.verdict_restated != expected:
        raise ModelRetry(f"The gate's verdict is '{expected}', not '{review.verdict_restated}'. Restate it.")
    return review


VALIDATORS: dict[str, Callable] = {
    **{kind: _validate_report for kind in SPECIALIST_STUDIES},
    "reviewer": _validate_review,
}


def build(model_factory: Callable[[str], Model]) -> dict[str, Agent]:
    """One Pydantic AI agent per roster entry, durable under DBOS, with its validators. Built before
    `DBOS.launch()` (the durability capability registers its steps by the agent's name)."""
    toolsets = {name: make() for name, make in TOOL_GROUPS.items()}
    agents: dict[str, Agent] = {}
    for name, spec in AGENTS.items():
        agent: Agent = Agent(
            model_factory(spec.role),
            name=f"gridforge-{name}",
            instructions=prompts.COMMON_RULES + "\n\n" + spec.instructions,
            deps_type=AgentDeps,
            output_type=spec.output_type,
            toolsets=[toolsets[g] for g in spec.tools],
            retries=2,
            capabilities=[DBOSDurability(event_stream_handler=on_event, parallel_execution_mode="sequential")],
        )
        if name in VALIDATORS:
            agent.output_validator(VALIDATORS[name])
        agents[name] = agent
    return agents
