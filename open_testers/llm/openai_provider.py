"""OpenAI provider.

Uses vision via a data: URL image and function calling with the same
take_action shape as the Claude provider so the executor stays uniform.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from .base import AgentAction, LLMProvider, StepContext


DEFAULT_MODEL = "gpt-4o"

SYSTEM_PROMPT = (
    "You are a browser-driving QA agent. Given the current page state, the "
    "test step, and project memory, choose ONE next action. Prefer text=... "
    "selectors over fragile CSS. Call the take_action function exactly once "
    "per turn. Return 'done' with success=True when the step is verified, "
    "'fail' with success=False on failure."
)

TAKE_ACTION_FUNCTION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "take_action",
        "description": (
            "Emit exactly one browser action. Use 'done' when verified, "
            "'fail' when blocked."
        ),
        "parameters": {
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
                },
                "selector": {"type": "string"},
                "value": {"type": "string"},
                "reasoning": {"type": "string"},
                "success": {"type": "boolean"},
            },
            "required": ["kind"],
        },
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


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str | None = None) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set; cannot construct OpenAIProvider."
            )
        self.model = model or os.environ.get("OPEN_TESTERS_OPENAI_MODEL", DEFAULT_MODEL)
        self.client = AsyncOpenAI(api_key=api_key)

    async def decide(self, ctx: StepContext) -> AgentAction:
        user_text = (
            f"Test: {ctx.test_title}\n"
            f"Step #{ctx.step_index} [{ctx.step_type}]: {ctx.step_title}\n"
            f"Page URL: {ctx.page_url}\n"
            f"Page title: {ctx.page_title}\n"
            f"Credentials available (labels only): "
            f"{', '.join(ctx.credentials_available) or '(none)'}\n\n"
            f"Project memories:\n{_memories_text(ctx.memories)}\n\n"
            f"DOM summary:\n{ctx.dom_summary or '(empty)'}\n"
        )

        user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        if ctx.screenshot_b64:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{ctx.screenshot_b64}"
                    },
                }
            )

        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            tools=[TAKE_ACTION_FUNCTION],
            tool_choice={"type": "function", "function": {"name": "take_action"}},
        )

        choice = response.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        for call in tool_calls:
            if call.function.name == "take_action":
                try:
                    data = json.loads(call.function.arguments)
                except json.JSONDecodeError as exc:
                    return AgentAction(
                        kind="fail",
                        reasoning=f"openai: tool args parse error: {exc}",
                        success=False,
                    )
                return AgentAction(
                    kind=data.get("kind", "fail"),
                    selector=data.get("selector"),
                    value=data.get("value"),
                    reasoning=data.get("reasoning", ""),
                    success=bool(data.get("success", True)),
                )

        return AgentAction(
            kind="fail",
            reasoning="openai: model did not emit a take_action tool call",
            success=False,
        )
