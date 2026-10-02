"""OpenRouter narration around the deterministic optimizer.

The LLM only phrases results the engine has already computed; it decides nothing:
  - justify             -> narrates the finished queue
  - narrate_diff        -> phrases a consequence diff between two runs
  - narrate_suggestion  -> phrases a "what would it take" unblock suggestion
"""

from __future__ import annotations

import os

from openai import OpenAI

from .config import (
    JUSTIFY_MODEL,
    JUSTIFY_SYSTEM_PROMPT,
    JUSTIFY_TEMPERATURE,
    NARRATE_DIFF_SYSTEM_PROMPT,
    OPENROUTER_BASE_URL,
    SUGGEST_SYSTEM_PROMPT,
)


def _client() -> OpenAI:
    """An OpenAI SDK client pointed at OpenRouter (reads OPENROUTER_API_KEY from the environment)."""
    return OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url=OPENROUTER_BASE_URL)


def justify(result_summary: str) -> str:
    """Write a narrative justification for the ordered queue (plain text)."""
    resp = _client().chat.completions.create(
        model=JUSTIFY_MODEL,
        temperature=JUSTIFY_TEMPERATURE,
        messages=[
            {"role": "system", "content": JUSTIFY_SYSTEM_PROMPT},
            {"role": "user", "content": result_summary},
        ],
    )
    return resp.choices[0].message.content


def narrate_diff(diff_summary: str) -> str:
    """Re-phrase a pre-computed consequence diff into one or two plain-text sentences.

    `diff_summary` is a prewritten text summary of the diff (capacity deltas, top project moves,
    network effects). The model only restates those figures; it computes nothing.
    """
    resp = _client().chat.completions.create(
        model=JUSTIFY_MODEL,
        temperature=JUSTIFY_TEMPERATURE,
        messages=[
            {"role": "system", "content": NARRATE_DIFF_SYSTEM_PROMPT},
            {"role": "user", "content": diff_summary},
        ],
    )
    return resp.choices[0].message.content


def narrate_suggestion(suggestion_summary: str) -> str:
    """Phrase a pre-computed unblock suggestion into one or two plain-text sentences.

    `suggestion_summary` restates the deterministic figures (the action, MW freed by 2030/2035, the
    projects connected). The model phrases them only — it computes nothing and must not imply the
    action is the cheapest or only fix.
    """
    resp = _client().chat.completions.create(
        model=JUSTIFY_MODEL,
        temperature=JUSTIFY_TEMPERATURE,
        messages=[
            {"role": "system", "content": SUGGEST_SYSTEM_PROMPT},
            {"role": "user", "content": suggestion_summary},
        ],
    )
    return resp.choices[0].message.content
