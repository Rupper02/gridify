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
from .tools import TOOL_GROUPS, AgentDeps, scope_instructions

# which studies each specialist may run (its remit; the tools refuse the rest)
SPECIALIST_STUDIES: dict[str, tuple[str, ...]] = {
    "thermal": ("hosting_capacity", "contingency_ranking"),
    "voltage": ("tap_margin", "hosting_capacity"),
    "demand_security": ("contingency_ranking", "structural_weak_points"),
    "boundary": ("gsp_margin_by_year",),
    "data_quality": ("data_quality",),
    "works": ("contingency_ranking",),
    "connections": ("connection_options",),
}


class AgentSpec(NamedTuple):
    role: str  # the model role (config.AGENT_MODELS)
    instructions: str
    tools: tuple[str, ...]  # TOOL_GROUPS keys
    output_type: Any
    studies: tuple[str, ...] = ()  # the studies its tools may run ("studies" group)


AGENTS: dict[str, AgentSpec] = {
    "steward": AgentSpec("steward", prompts.STEWARD_TRIAGE, ("read",), StewardPlan),
    # the brief restates the specialists' reports it is handed: with read tools it re-ran the merge check (solving the
    # parent's years for minutes under the gate) to say nothing more
    "steward_brief": AgentSpec("steward", prompts.STEWARD_BRIEF, (), HealthBrief),
    **{kind: AgentSpec("specialist", prompts.specialist_prompt(kind), ("read", "studies", "filing"), SpecialistReport, SPECIALIST_STUDIES[kind])
       for kind in SPECIALIST_STUDIES},
    "reviewer": AgentSpec("reviewer", prompts.REVIEWER, ("read", "studies"), ReviewComment, ("contingency_ranking",)),
    "answerer": AgentSpec("answerer", prompts.ANSWERER, ("read", "studies", "proposals"), [str, DeferredToolRequests],
                          tuple(dict.fromkeys(SPECIALIST_STUDIES["thermal"] + SPECIALIST_STUDIES["voltage"] + SPECIALIST_STUDIES["demand_security"]
                                              + SPECIALIST_STUDIES["boundary"] + SPECIALIST_STUDIES["data_quality"] + SPECIALIST_STUDIES["connections"] + ("best_window",)))),
}
SPECIALISTS: tuple[str, ...] = tuple(SPECIALIST_STUDIES)


# --- the validators that keep figures honest ---------------------------------------------------------------
def _steps_text(steps: list[dict]) -> str:
    return "\n".join(f"- {s['step_id']} ({s['tool']}): items 0..{len(s['result'].get('items') or []) - 1}" for s in steps) or "- none"


def _validate_report(ctx: RunContext[AgentDeps], report: SpecialistReport) -> SpecialistReport:
    """Every finding in the report must name a study step of THIS run and an item it has (the server copies the
    figures); a step named by its tool-call id alone is completed to the full id, anything else is sent back with the
    run's steps listed. A specialist that filed nothing (neither through `file_finding` nor here) while its studies
    returned items is sent back once with them."""
    ev = ctx.deps.h.evidence
    steps = ev.study_steps(ctx.deps.run_id)
    bad = []
    for f in report.findings:
        full = ev.resolve_step(f.step_id, steps)
        if full is None:
            bad.append(f"{f.step_id} is not a study step of this run")
            continue
        f.step_id = full
        n = len(next(s for s in steps if s["step_id"] == full)["result"].get("items") or [])
        if not (0 <= f.item_index < n):
            bad.append(f"{full} has no item {f.item_index} (it has {n})")
    if bad:
        raise ModelRetry("Some findings do not point at a recorded study item: " + "; ".join(bad)
                         + ". Answer with the SpecialistReport tool again; a finding's step_id is one of this run's study steps "
                         "(the full id, or just its tool-call id after the last colon) and item_index one of its items:\n" + _steps_text(steps))
    if not report.findings and not ctx.deps.context.get("filed") and not ctx.deps.context.get("asked_to_file"):
        # the studies measured things and the model filed nothing: once, send it back with the items (a filed finding is
        # bound to its step and shows in the ledger with an evidence link; prose is not)
        rank = {"breach": 0, "warn": 1, "info": 2}
        items = sorted(((rank.get(it.get("severity"), 3), s["step_id"], it) for s in steps for it in (s["result"].get("items") or [])),
                       key=lambda x: (x[0], x[1]))
        if items:
            ctx.deps.context["asked_to_file"] = True
            listed = "\n".join(f"- step {sid} item {it.get('index')} [{it.get('severity')}]: {str(it.get('message'))[:160]}" for _, sid, it in items[:8])
            raise ModelRetry("Your studies returned items and you filed no finding. Call file_finding for the ones worth an engineer's "
                             "attention (every warn or breach item; what your job says to file even when it is info), each with its step_id, "
                             "item_index, your message and action, then answer with the SpecialistReport tool again, or say in `summary` why "
                             "none is worth filing:\n" + listed)
    return report


def _identity(f: dict) -> tuple:
    return (f.get("kind"), None if f.get("element_id") is None else str(f["element_id"]), f.get("fingerprint") or None)


def _validate_review(ctx: RunContext[AgentDeps], review: ReviewComment) -> ReviewComment:
    """The reviewer restates the gate, nothing more and nothing less: every blocker it lists must be one
    the merge check produced (same kind, element and fingerprint: the gate's grouped items, `tools.merge_summary`)
    and every gate blocker must be there. The retry names only what is off, never the whole gate again."""
    gate = ctx.deps.context.get("merge_check") or {}
    want = {_identity(f) for f in gate.get("blockers", [])}
    got = {_identity(b.model_dump()) for b in review.blockers}
    unknown = got - want
    missing = want - got
    if unknown or missing:
        raise ModelRetry("Restate exactly the gate's blockers, one Restated per item, each with its kind, element_id and fingerprint "
                         "copied from the gate in your prompt (kind, element_id, fingerprint). "
                         + (f"Not from the gate: {sorted(map(str, unknown))}. " if unknown else "")
                         + (f"Missing: {sorted(map(str, missing))}." if missing else ""))
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
            retries=3,  # a typed output takes a model two tries at times (an id to copy, a text reply instead of the tool call)
            capabilities=[DBOSDurability(event_stream_handler=on_event, parallel_execution_mode="sequential")],
        )
        agent.instructions(scope_instructions)  # every run is told which branch it works on
        if name in VALIDATORS:
            agent.output_validator(VALIDATORS[name])
        agents[name] = agent
    return agents
