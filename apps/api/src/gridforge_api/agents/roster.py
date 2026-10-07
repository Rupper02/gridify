"""The roster: which agents exist, what each may do, and how they are built.

Two roles. The **answerer** takes an operator's question, plans typed queries over the engine's reads and
studies, cites every step and proposes what the operator may approve. The **digest** writes the engineer's
note after a run from the deterministic digest the engine computed: one call, no tools, every figure bound
by value to the digest. Each is one `AgentSpec` (a registry entry); `build` turns the roster into Pydantic
AI agents with the DBOS durability capability.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.durable_exec.dbos import DBOSDurability
from pydantic_ai.models import Model

from . import prompts
from .streaming import on_event
from .tools import TOOL_GROUPS, AgentDeps, scope_instructions


class AgentSpec(NamedTuple):
    role: str  # the model role (config.AGENT_MODELS)
    instructions: str
    tools: tuple[str, ...]  # TOOL_GROUPS keys
    output_type: Any
    studies: tuple[str, ...] = ()  # the studies its tools may run ("studies" group)


# the studies an answer may run: every registry study the engine offers to agents
ANSWERER_STUDIES: tuple[str, ...] = ("hosting_capacity", "contingency_ranking", "tap_margin", "structural_weak_points",
                                     "gsp_margin_by_year", "data_quality", "connection_options", "best_window")

AGENTS: dict[str, AgentSpec] = {
    "answerer": AgentSpec("answerer", prompts.COMMON_RULES + "\n\n" + prompts.ANSWERER, ("read", "studies", "proposals"),
                          [str, DeferredToolRequests], ANSWERER_STUDIES),
    "digest": AgentSpec("digest", prompts.DIGEST, (), str),
}


def build(model_factory: Callable[[str], Model]) -> dict[str, Agent]:
    """One Pydantic AI agent per roster entry, durable under DBOS. Built before `DBOS.launch()` (the durability
    capability registers its steps by the agent's name)."""
    toolsets = {name: make() for name, make in TOOL_GROUPS.items()}
    agents: dict[str, Agent] = {}
    for name, spec in AGENTS.items():
        agent: Agent = Agent(
            model_factory(spec.role),
            name=f"gridforge-{name}",
            instructions=spec.instructions,
            deps_type=AgentDeps,
            output_type=spec.output_type,
            toolsets=[toolsets[g] for g in spec.tools],
            retries=2,
            capabilities=[DBOSDurability(event_stream_handler=on_event, parallel_execution_mode="sequential")],
        )
        if spec.tools:
            agent.instructions(scope_instructions)  # a run with tools is told which branch it works on
        agents[name] = agent
    return agents
