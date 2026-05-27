"""Local Ollama provider.

Hits /api/chat with format=json so the model returns structured output we can
parse directly into AgentAction. No tool-use protocol (Ollama models vary), so
we rely on JSON-mode instead.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base import AgentAction, LLMProvider, StepContext


DEFAULT_MODEL = "llava"
DEFAULT_HOST = "http://localhost:11434"
REQUEST_TIMEOUT_S = 60.0

SYSTEM_PROMPT = (
    "You are a browser-driving QA agent. Given the page state, the test step, "
    "and project memory, respond with ONE next action. "
    "Respond ONLY with a single JSON object matching this schema (no prose, "
    "no markdown):\n"
    "{\n"
    '  "kind": "click|fill|press|navigate|wait|scroll|assert_visible|'
    'assert_text|use_credential|upload_file|done|fail",\n'
    '  "selector": "<optional CSS or text= selector>",\n'
    '  "value": "<optional text/url/key>",\n'
    '  "reasoning": "<short justification>",\n'
    '  "success": <true|false>\n'
    "}\n"
    "Prefer text=... selectors over fragile CSS. Use kind=done with "
    "success=true when the step is verified, kind=fail with success=false "
    "on failure."
)


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


class OllamaProvider(LLMProvider):
    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self.model = model or os.environ.get("OPEN_TESTERS_OLLAMA_MODEL", DEFAULT_MODEL)
        self.host = (host or os.environ.get("OPEN_TESTERS_OLLAMA_HOST", DEFAULT_HOST)).rstrip("/")

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

        user_msg: dict[str, Any] = {"role": "user", "content": user_text}
        if ctx.screenshot_b64:
            user_msg["images"] = [ctx.screenshot_b64]

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                user_msg,
            ],
            "format": "json",
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
                resp = await client.post(f"{self.host}/api/chat", json=payload)
                resp.raise_for_status()
                body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return AgentAction(
                kind="fail",
                reasoning=f"ollama transport error: {exc}",
                success=False,
            )

        content = (body.get("message") or {}).get("content", "")
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            return AgentAction(
                kind="fail",
                reasoning=f"ollama parse error: {exc}",
                success=False,
            )

        return AgentAction(
            kind=data.get("kind", "fail"),
            selector=data.get("selector"),
            value=data.get("value"),
            reasoning=data.get("reasoning", ""),
            success=bool(data.get("success", True)),
        )
