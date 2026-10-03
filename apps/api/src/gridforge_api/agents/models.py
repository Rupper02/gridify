"""The one place that knows OpenRouter: a model per agent role, or nothing when there is no key.

The harness takes a `model_factory(role) -> Model`; this builds the real one. Tests pass scripted
`FunctionModel`s instead, so nothing else in the harness imports a provider.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from pydantic_ai.models import Model

from ..config import AGENT_MODELS, OPENROUTER_APP

ModelFactory = Callable[[str], Model]


def openrouter_model_factory() -> ModelFactory | None:
    """A factory of OpenRouter models by role, or None without `OPENROUTER_API_KEY` (agents off)."""
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return None
    from openai import AsyncOpenAI
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    from gridforge_optimizer.config import OPENROUTER_BASE_URL

    # provider-side retries off: the durable runtime retries steps itself, and two retry layers multiply
    client = AsyncOpenAI(api_key=key, base_url=OPENROUTER_BASE_URL, max_retries=0)
    provider = OpenRouterProvider(api_key=key, app_url=OPENROUTER_APP["app_url"], app_title=OPENROUTER_APP["app_title"], openai_client=client)
    cache: dict[str, Model] = {}

    def factory(role: str) -> Model:
        name = AGENT_MODELS.get(role, AGENT_MODELS["specialist"])
        if name not in cache:
            cache[name] = OpenRouterModel(name, provider=provider, settings={"temperature": 0.2})
        return cache[name]

    return factory
