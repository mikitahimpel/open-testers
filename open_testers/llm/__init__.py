"""LLM provider package.

Exposes the provider contract types and a factory that resolves a provider by
name or via the OPEN_TESTERS_LLM environment variable.
"""

from __future__ import annotations

import os

from .base import AgentAction, LLMProvider, StepContext


_DEFAULT = "stub"
_VALID = ("claude", "openai", "ollama", "stub")


def get_provider(name: str | None = None) -> LLMProvider:
    """Resolve a provider by name or env var OPEN_TESTERS_LLM.

    Accepted names: 'claude', 'openai', 'ollama', 'stub'. Default: 'stub'.
    Providers that require API keys raise RuntimeError at construction time
    when the key env var is missing.
    """

    resolved = (name or os.environ.get("OPEN_TESTERS_LLM") or _DEFAULT).lower()
    if resolved not in _VALID:
        raise ValueError(
            f"Unknown LLM provider '{resolved}'. Valid: {', '.join(_VALID)}."
        )

    if resolved == "stub":
        from .stub import StubProvider

        return StubProvider()
    if resolved == "claude":
        from .claude import ClaudeProvider

        return ClaudeProvider()
    if resolved == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider()
    if resolved == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider()

    raise ValueError(f"Unreachable: provider '{resolved}'")


__all__ = ["LLMProvider", "StepContext", "AgentAction", "get_provider"]
