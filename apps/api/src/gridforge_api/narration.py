"""LLM narration. The engine decides; narration only restates its figures.

The API depends on the `Narrator` protocol, not on OpenRouter: the composition root wires the
OpenRouter one (the key is required at startup), tests inject a scripted one, and the summaries
below are the only text the model ever sees.
"""

from typing import Protocol

from gridforge_optimizer import llm as opt_llm


class Narrator(Protocol):
    def justify(self, summary: str) -> str: ...
    def narrate_diff(self, summary: str) -> str: ...
    def narrate_suggestion(self, summary: str) -> str: ...


class OpenRouterNarrator:
    """Narration through the optimizer's OpenRouter client (needs OPENROUTER_API_KEY)."""

    def justify(self, summary: str) -> str:
        return opt_llm.justify(summary)

    def narrate_diff(self, summary: str) -> str:
        return opt_llm.narrate_diff(summary)

    def narrate_suggestion(self, summary: str) -> str:
        return opt_llm.narrate_suggestion(summary)


def safely(fn, summary: str) -> str:
    """Narration is garnish on an engine result: a failed call (network, quota) yields an empty
    string rather than failing the run whose figures are already decided."""
    try:
        return fn(summary)
    except Exception:
        return ""


# --- summaries: plain text restating engine figures only -------------------------------------
def summarize_queue(result) -> str:
    """Render the ordered queue as plain text for the narration prompt."""
    rows = []
    for q in result.queue:
        reason = f" — {q.reason.message}" if q.reason else ""
        rows.append(
            f"#{q.rank or '-'} {q.request_id}: {q.status}; {q.technology} {q.rating_mw} MW at bus "
            f"{q.bus_id}; readiness={q.readiness_score}, grid_need={q.grid_need}{reason}"
        )
    return "Connection queue (ordered):\n" + "\n".join(rows)


def summarize_diff(d) -> str:
    """Render a consequence diff as plain text for the narration prompt (restates figures only)."""
    h = d.headline
    lines = [
        f"Baseline: {d.base_label}",
        f"Proposed: {d.head_label}",
        f"MW connected by 2030: {h['mw_2030_base']} -> {h['mw_2030_head']} ({h['mw_2030_delta']:+})",
        f"MW connected by 2035: {h['mw_2035_base']} -> {h['mw_2035_head']} ({h['mw_2035_delta']:+})",
        f"Projects: {h['n_accelerated']} accelerated, {h['n_slipped']} slipped, "
        f"{h['n_added']} added, {h['n_dropped']} dropped",
    ]
    for p in [p for p in d.projects if p.change != "unchanged"][:5]:
        lines.append(
            f"- {p.request_id} ({p.technology} {p.rating_mw} MW): "
            f"{p.base_status} -> {p.head_status} [{p.change}]"
        )
    for ph in d.phases:
        if ph.newly_overloaded_line_ids or ph.cleared_line_ids:
            lines.append(
                f"Phase {ph.phase}: newly overloaded {ph.newly_overloaded_line_ids}, "
                f"cleared {ph.cleared_line_ids}"
            )
    for w in d.works:
        if w.change in ("worse", "better"):
            lines.append(f"Planned work {w.outage_id} ({w.year}): {w.consequence}")
    return "\n".join(lines)


def summarize_suggestion(s, base) -> str:
    """Plain-text summary of a deterministic suggestion for the narration prompt (figures only)."""
    rating = {q.request_id: q.rating_mw for q in base.queue}
    connects = ", ".join(
        f"{rid} ({rating.get(rid, '?')} MW)" for rid in s.newly_connected_project_ids
    ) or "no additional projects"
    return (
        f"Deferred project(s): {', '.join(s.blocked_project_ids)}.\n"
        f"Binding constraint: {s.target_type} {s.target_element_id}.\n"
        f"Action: {s.action}.\n"
        f"Connects the blocked project: "
        f"{'yes' if s.connects_target else 'no — further reinforcement needed'}.\n"
        f"Frees ~{s.freed_mw_2030} MW by 2030 and ~{s.freed_mw_2035} MW by 2035.\n"
        f"Projects that connect under it: {connects}."
    )
