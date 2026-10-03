"""What an agent run streams to the planner: tokens, tool calls and results tagged with the planning
stage they belong to (PLAN · ASSEMBLE · RUN · CHECK · CITE), each carrying the step id a figure can be
traced to. The sink is injected (a DBOS stream in a workflow, a list in a test)."""

from __future__ import annotations

from collections.abc import AsyncIterable

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    AgentStreamEvent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)

from .tools import AgentDeps

# the planning stage a tool belongs to, by name prefix (first match wins; "" is the default)
STAGE_BY_TOOL_PREFIX: tuple[tuple[str, str], ...] = (
    ("study_", "RUN"),
    ("merge_check", "CHECK"),
    ("findings", "CHECK"),
    ("propose_", "PROPOSE"),
    ("", "ASSEMBLE"),
)


def stage_of(tool: str) -> str:
    return next(stage for prefix, stage in STAGE_BY_TOOL_PREFIX if tool.startswith(prefix))


def map_event(ev: AgentStreamEvent, deps: AgentDeps) -> dict | None:
    """One stream event as the planner's trace needs it, or None for events it does not show."""
    if isinstance(ev, PartDeltaEvent) and isinstance(ev.delta, TextPartDelta):
        return {"t": "token", "text": ev.delta.content_delta}
    if isinstance(ev, PartStartEvent) and isinstance(ev.part, TextPart) and ev.part.content:
        return {"t": "token", "text": ev.part.content}
    if isinstance(ev, FunctionToolCallEvent):
        p = ev.part
        return {"t": "tool_call", "tool": p.tool_name, "stage": stage_of(p.tool_name), "step_id": f"{deps.run_id}:{p.tool_call_id}",
                "args": p.args_as_dict()}
    if isinstance(ev, FunctionToolResultEvent):
        content = ev.content if isinstance(ev.content, dict) else getattr(ev.part, "content", None)
        summary = content.get("summary") if isinstance(content, dict) else None
        step_id = content.get("step_id") if isinstance(content, dict) else None
        return {"t": "tool_result", "tool": getattr(ev.part, "tool_name", ""), "step_id": step_id or f"{deps.run_id}:{getattr(ev.part, 'tool_call_id', '')}",
                "summary": summary or "", "solves": content.get("solves", 0) if isinstance(content, dict) else 0}
    if isinstance(ev, FinalResultEvent):
        return {"t": "cite", "stage": "CITE"}
    return None


async def on_event(ctx: RunContext[AgentDeps], stream: AsyncIterable[AgentStreamEvent]) -> None:
    """The agents' event stream handler (runs inside a durable step): map and emit."""
    deps = ctx.deps
    async for ev in stream:
        out = map_event(ev, deps)
        if out is not None:
            out["seq"] = deps.next_seq()
            await deps.emit_async(out)
