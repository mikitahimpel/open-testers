from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class StepContext:
    """Everything the LLM needs to decide the next browser action."""

    step_index: int
    step_type: str  # "act" | "assert" | "login" | "files" | "screenshot"
    step_title: str
    screenshot_b64: str  # current page screenshot, base64-encoded PNG
    page_url: str
    page_title: str
    dom_summary: str  # short text summary of interactive elements (executor builds this)
    memories: list[dict]  # project memory entries: [{category, title, content, importance}]
    test_title: str
    project_url: Optional[str]
    credentials_available: list[str]  # labels only, never the secrets
    extra: dict[str, Any] = field(default_factory=dict)  # step-type-specific


@dataclass
class AgentAction:
    """One concrete action the agent wants the executor to perform."""

    kind: str  # "click" | "fill" | "press" | "navigate" | "wait" | "scroll" | "assert_visible" | "assert_text" | "use_credential" | "upload_file" | "done" | "fail"
    selector: Optional[str] = None  # CSS selector or "text=...", optional
    value: Optional[str] = None  # text to fill, key to press, URL to nav, expected text, etc.
    reasoning: str = ""  # short why
    success: bool = True  # for "done" actions, did the step pass? for "fail", set False


class LLMProvider(ABC):
    @abstractmethod
    async def decide(self, ctx: StepContext) -> AgentAction:
        """Given the current step + page state, return ONE action to execute next.

        The executor loops: decide -> execute -> screenshot -> decide,
        until kind in ('done', 'fail').
        """
        ...
