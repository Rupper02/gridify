"""Step citations in agent prose, normalised before a text is stored. The planner renders `[step <id>]` as a numbered
evidence chip (and `[same step]` as a repeat of the last one), so every bracketed reference to a recorded step must take
exactly that form, and a bracket that cites nothing recorded (an abbreviated or invented id, a tool name) must go rather
than print as 80 characters of raw id."""

from __future__ import annotations

import re

_BRACKETS = re.compile(r"[\[【]([^\]】\n]*)[\]】]")
# what a bracket that is trying to be a citation looks like: the word "step", a tool-call id, a workflow id's shape
_CITATION_LIKE = re.compile(r"\bsteps?\b|toolu_|_run:|snapshot::|:\d+:[a-z_]+", re.IGNORECASE)
_STEP_REF = re.compile(r"\s*\[(?:step [^\]\n]+|same step)\]")


def normalize_citations(text: str, step_ids: list[str]) -> str:
    """Every bracketed reference to one of `step_ids` (by its full id, or by its tool-call suffix, which models abbreviate
    to) becomes `[step <full id>]`, one bracket per step; a bracket that looks like a citation but names no recorded step
    is removed; ordinary brackets ("[same step]", a markdown link's text) stay as they are."""
    if not text or not step_ids:
        return text
    by_suffix = {s.rsplit(":", 1)[-1]: s for s in step_ids if ":" in s}

    def one(m: re.Match) -> str:
        inner = m.group(1)
        if inner.strip().lower() == "same step":
            return m.group(0)
        found = [s for s in step_ids if s in inner]
        for suffix, sid in by_suffix.items():
            if suffix in inner and sid not in found:
                found.append(sid)
        if found:
            return " ".join(f"[step {s}]" for s in found)
        return "" if _CITATION_LIKE.search(inner) else m.group(0)

    out = _BRACKETS.sub(one, text)
    out = re.sub(r"(?<=\S) {2,}(?=\S)", " ", out)  # the gap a removed bracket leaves mid-line (list indentation is untouched)
    return re.sub(r" +([.,;:])", r"\1", out)


def strip_citations(text: str) -> str:
    """The text without its step citations: for a run's one-line summary (the runs list), where a chip cannot render
    and an 80-character id would print raw."""
    return re.sub(r" +([.,;:])", r"\1", _STEP_REF.sub("", text or "")).strip()
