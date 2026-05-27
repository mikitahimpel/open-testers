"""Deterministic, no-network provider that drives --dry-run mode.

The executor calls decide() repeatedly per step until kind is done or fail.
We track per-step call counts so the same step can yield a navigate-then-done
sequence on the first step of an example test.
"""

from .base import AgentAction, LLMProvider, StepContext


_NAV_HINTS = ("open", "navigate", "go to", "http://", "https://")


def _looks_like_navigation(title: str) -> bool:
    lower = title.lower()
    return any(hint in lower for hint in _NAV_HINTS)


class StubProvider(LLMProvider):
    def __init__(self) -> None:
        self._calls_per_step: dict[int, int] = {}

    async def decide(self, ctx: StepContext) -> AgentAction:
        n = self._calls_per_step.get(ctx.step_index, 0)
        self._calls_per_step[ctx.step_index] = n + 1

        if ctx.step_type == "act":
            if n == 0 and ctx.project_url and _looks_like_navigation(ctx.step_title):
                return AgentAction(
                    kind="navigate",
                    value=ctx.project_url,
                    reasoning="stub: navigating to project URL based on step title",
                )
            return AgentAction(
                kind="done",
                success=True,
                reasoning="stub: act step complete",
            )

        if ctx.step_type in ("screenshot", "assert", "login", "files"):
            return AgentAction(
                kind="done",
                success=True,
                reasoning=f"stub: {ctx.step_type} step complete",
            )

        return AgentAction(
            kind="done",
            success=True,
            reasoning=f"stub: unknown step_type '{ctx.step_type}', defaulting to done",
        )
