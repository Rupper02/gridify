"""OpenRouter wrappers: the LLM / decisions calls around the deterministic optimizer.

Each call uses the model suited to its job:
  - extract_readiness_checklist  -> LLM extracts stated facts (then readiness.py scores them)
  - score_strategic_fit          -> Jev decisions model judges 'is this the right addition',
                                    grounded in the measured grid signal, and returns a
                                    CALIBRATED confidence (not an LLM's self-reported guess)
  - justify                      -> LLM narrates the finished queue
"""

from __future__ import annotations

import json
import os
import urllib.request

from openai import OpenAI

from .config import (
    DECISIONS_TIMEOUT_S,
    DECISIONS_URL,
    JEV_MODEL,
    JUSTIFY_MODEL,
    JUSTIFY_SYSTEM_PROMPT,
    JUSTIFY_TEMPERATURE,
    LLM_TEMPERATURE,
    NARRATE_DIFF_SYSTEM_PROMPT,
    OPENROUTER_BASE_URL,
    READINESS_CHECKLIST_RESPONSE_FORMAT,
    READINESS_EXTRACTION_SYSTEM_PROMPT,
    SCORING_MODEL,
    STRATEGIC_CRITERIA,
    STRATEGIC_FIT_VALUE,
    STRATEGIC_INSTRUCTIONS,
    STRATEGIC_RESPONSE_FORMAT,
    STRATEGIC_SYSTEM_PROMPT,
    SUGGEST_SYSTEM_PROMPT,
)


def _client() -> OpenAI:
    """An OpenAI SDK client pointed at OpenRouter (reads OPENROUTER_API_KEY from the environment)."""
    return OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url=OPENROUTER_BASE_URL)


def extract_readiness_checklist(text: str) -> dict:
    """Extract the factual Gate-2 readiness milestones from the application text (no scoring).

    Returns the checklist dict; feed it to readiness.score_from_checklist for the score.
    """
    resp = _client().chat.completions.create(
        model=SCORING_MODEL,
        temperature=LLM_TEMPERATURE,
        messages=[
            {"role": "system", "content": READINESS_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=READINESS_CHECKLIST_RESPONSE_FORMAT,
    )
    return json.loads(resp.choices[0].message.content)


def score_strategic_fit(state: dict) -> dict:
    """Judge strategic fit with Jev, grounded in the grid signal carried by `state`.

    `state` is any JSON-able dict describing the project + its measured local grid signal
    (e.g. technology, rating_mw, bus_id, grid_need). Returns
    {strategic_fit (0..1), strategic_confidence (0..1 or None), strategic_rationale}.
    Falls back to a chat call only if the decisions endpoint is unreachable.
    """
    body = {
        "model": JEV_MODEL,
        "state": state,
        "questions": {
            "strategic_fit": {
                "type": "choice",
                "instructions": STRATEGIC_INSTRUCTIONS,
                "criteria": STRATEGIC_CRITERIA,
            }
        },
    }
    req = urllib.request.Request(
        DECISIONS_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=DECISIONS_TIMEOUT_S) as r:
            ans = json.loads(r.read())["answers"]["strategic_fit"]
        probs = ans.get("probabilities", {})
        # expected value over the probability distribution -> continuous 0..1
        score = round(sum(STRATEGIC_FIT_VALUE[k] * probs.get(k, 0.0) for k in STRATEGIC_FIT_VALUE), 4)
        rationale = (
            f"Jev judged strategic fit '{ans['choice']}' "
            f"(high {probs.get('high', 0):.2f} / medium {probs.get('medium', 0):.2f} / "
            f"low {probs.get('low', 0):.2f})"
        )
        return {
            "strategic_fit": score,
            "strategic_confidence": round(float(ans.get("confidence", 0.0)), 4),
            "strategic_rationale": rationale,
        }
    except Exception:
        return _score_strategic_fit_chat(state)


def _score_strategic_fit_chat(state: dict) -> dict:
    """Degradation path: a plain chat call when the decisions endpoint is unavailable."""
    resp = _client().chat.completions.create(
        model=SCORING_MODEL,
        temperature=LLM_TEMPERATURE,
        messages=[
            {"role": "system", "content": STRATEGIC_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(state)},
        ],
        response_format=STRATEGIC_RESPONSE_FORMAT,
    )
    data = json.loads(resp.choices[0].message.content)
    return {
        "strategic_fit": round(float(data["strategic_fit"]), 4),
        "strategic_confidence": None,  # a chat guess carries no calibrated confidence
        "strategic_rationale": data["strategic_rationale"],
    }


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
