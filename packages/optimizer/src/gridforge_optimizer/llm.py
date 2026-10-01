"""OpenRouter wrappers: score a project's readiness from text, and justify the final queue.

The optimizer is deterministic; the LLM only scores inputs and narrates outputs.
"""

from __future__ import annotations

import json
import os

from openai import OpenAI

from .config import (
    JUSTIFY_MODEL,
    JUSTIFY_SYSTEM_PROMPT,
    OPENROUTER_BASE_URL,
    SCORING_MODEL,
    SCORING_RESPONSE_FORMAT,
    SCORING_SYSTEM_PROMPT,
)


def _client() -> OpenAI:
    return OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url=OPENROUTER_BASE_URL)


def score_readiness(text: str) -> dict:
    """Return {readiness_score, readiness_rationale, strategic_fit, strategic_rationale}."""
    resp = _client().chat.completions.create(
        model=SCORING_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SCORING_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=SCORING_RESPONSE_FORMAT,
    )
    return json.loads(resp.choices[0].message.content)


def justify(result_summary: str) -> str:
    """Write a narrative justification for the ordered queue (plain text)."""
    resp = _client().chat.completions.create(
        model=JUSTIFY_MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": JUSTIFY_SYSTEM_PROMPT},
            {"role": "user", "content": result_summary},
        ],
    )
    return resp.choices[0].message.content
