"""Anthropic Claude provider.

Uses vision (base64 image block) plus a single tool_use definition that mirrors
AgentAction. Two cache breakpoints are placed: one on the static system prompt
and one on the per-project memories block, which changes rarely.
"""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from .base import AgentAction, LLMProvider, StepContext


DEFAULT_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "You are a browser-driving QA agent. Given the current page state, the "
    "test step, and project memory, choose ONE next action. Prefer text=... "
    "selectors over fragile CSS. Call the take_action tool exactly once per "
    "turn. Return 'done' with success=True when the step is verified, 'fail' "
    "with success=False on failure."
)

TAKE_ACTION_TOOL: dict[str, Any] = {
    "name": "take_action",
    "description": (
        "Emit exactly one browser action for the executor to perform. "
        "Use 'done' when the current step is verified, 'fail' when blocked."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": [
                    "click",
                    "fill",
                    "press",
                    "navigate",
                    "wait",
                    "scroll",
                    "assert_visible",
                    "assert_text",
                    "use_credential",
                    "upload_file",
                    "done",
                    "fail",
                ],
                "description": "Action kind for the executor.",
            },
            "selector": {
                "type": "string",
                "description": "Optional CSS or text= selector.",
            },
            "value": {
                "type": "string",
                "description": "Optional value: text to fill, URL to nav, expected text, etc.",
            },
            "reasoning": {
                "type": "string",
                "description": "Short justification for this action.",
            },
            "success": {
                "type": "boolean",
                "description": "For 'done'/'fail' actions: pass/fail result.",
            },
        },
        "required": ["kind"],
    },
}


def _memories_text(memories: list[dict]) -> str:
    if not memories:
        return "(no project memories)"
    lines = []
    for m in memories:
        lines.append(
            f"- [{m.get('category', '?')}] {m.get('title', '')} "
            f"(importance={m.get('importance', '?')})\n  {m.get('content', '')}"
        )
    return "\n".join(lines)


class ClaudeProvider(LLMProvider):
    def __init__(self, model: str | None = None) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; cannot construct ClaudeProvider."
            )
        self.model = model or os.environ.get("OPEN_TESTERS_CLAUDE_MODEL", DEFAULT_MODEL)
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def decide(self, ctx: StepContext) -> AgentAction:
        user_text = (
            f"Test: {ctx.test_title}\n"
            f"Step #{ctx.step_index} [{ctx.step_type}]: {ctx.step_title}\n"
            f"Page URL: {ctx.page_url}\n"
            f"Page title: {ctx.page_title}\n"
            f"Credentials available (labels only): "
            f"{', '.join(ctx.credentials_available) or '(none)'}\n\n"
            f"DOM summary:\n{ctx.dom_summary or '(empty)'}\n"
        )

        user_content: list[dict[str, Any]] = []
        # Memories live in their own block so they can be a cache breakpoint
        # independent of the rapidly-changing per-step state.
        user_content.append(
            {
                "type": "text",
                "text": "Project memories:\n" + _memories_text(ctx.memories),
                "cache_control": {"type": "ephemeral"},
            }
        )
        user_content.append({"type": "text", "text": user_text})
        if ctx.screenshot_b64:
            user_content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": ctx.screenshot_b64,
                    },
                }
            )

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[TAKE_ACTION_TOOL],
            tool_choice={"type": "tool", "name": "take_action"},
            messages=[{"role": "user", "content": user_content}],
        )

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "take_action":
                data = block.input if isinstance(block.input, dict) else json.loads(block.input)
                return AgentAction(
                    kind=data.get("kind", "fail"),
                    selector=data.get("selector"),
                    value=data.get("value"),
                    reasoning=data.get("reasoning", ""),
                    success=bool(data.get("success", True)),
                )

        return AgentAction(
            kind="fail",
            reasoning="claude: model did not emit a take_action tool_use block",
            success=False,
        )
