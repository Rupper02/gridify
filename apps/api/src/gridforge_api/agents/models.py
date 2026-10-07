"""The one place that knows OpenRouter: a model per agent role.

The harness takes a `model_factory(role) -> Model`; this builds the real one from the key the API
requires at startup (`config.require_openrouter_key`). Tests pass scripted `FunctionModel`s instead,
so nothing else in the harness imports a provider.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic_ai.models import Model

from ..config import AGENT_MODELS, AGENT_RUN_BUDGET, OPENROUTER_APP

ModelFactory = Callable[[str], Model]


def openrouter_model_factory(key: str) -> ModelFactory:
    """A factory of OpenRouter models by role, on `key`."""
    from openai import AsyncOpenAI, Timeout
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    from gridforge_optimizer.config import OPENROUTER_BASE_URL

    # one client-side retry, and a connect timeout a network blip survives (the SDK's 5 s default once ended a note's
    # sweep on a single ConnectTimeout). The durable runtime does not retry a failed model request (a DBOS step without
    # retries), so this is the only retry layer; the 600 s request timeout is the SDK's own.
    client = AsyncOpenAI(api_key=key, base_url=OPENROUTER_BASE_URL, max_retries=1, timeout=Timeout(600.0, connect=20.0))
    provider = OpenRouterProvider(api_key=key, app_url=OPENROUTER_APP["app_url"], app_title=OPENROUTER_APP["app_title"], openai_client=client)
    cache: dict[str, Model] = {}

    def factory(role: str) -> Model:
        name = AGENT_MODELS.get(role, AGENT_MODELS["answerer"])
        if name not in cache:
            cache[name] = OpenRouterModel(name, provider=provider, settings={"temperature": 0.2, "max_tokens": AGENT_RUN_BUDGET["max_output_tokens"]})
        return cache[name]

    return factory
