"""Playwright-driven executor for open-testers."""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, async_playwright

from open_testers.llm.base import AgentAction, LLMProvider, StepContext
from open_testers.schema import TestDefinition


# JavaScript run in the page to produce a compact summary of visible interactive
# elements. Returns a list of strings; the executor caps to MAX_DOM_ENTRIES.
_DOM_SUMMARY_JS = r"""
() => {
  const sel = 'button, a, input, select, textarea, [role="button"], [role="link"]';
  const out = [];
  const nodes = document.querySelectorAll(sel);
  for (const el of nodes) {
    if (out.length >= 50) break;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const tag = el.tagName.toLowerCase();
    const label =
      el.getAttribute('aria-label') ||
      el.getAttribute('alt') ||
      el.getAttribute('title') ||
      (el.innerText || '').trim().split('\n')[0] ||
      el.getAttribute('placeholder') ||
      el.getAttribute('value') ||
      '';
    const trimmed = label.length > 80 ? label.slice(0, 80) + '…' : label;
    out.push(`<${tag}>${trimmed}`);
  }
  return out;
}
"""

MAX_DOM_ENTRIES = 50


@dataclass
class StepResult:
    step_index: int
    type: str
    title: str
    status: str  # "pass" | "fail" | "skipped"
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    duration_ms: int = 0
    actions: list[dict] = field(default_factory=list)


@dataclass
class RunResult:
    run_id: str
    test_title: str
    status: str  # "pass" | "fail"
    output_dir: str
    video_path: Optional[str]
    steps: list[StepResult]
    started_at: str
    finished_at: str


class Runner:
    def __init__(
        self,
        test: TestDefinition,
        llm: LLMProvider,
        output_root: Path,
        memories: Optional[list[dict]] = None,
        credentials_available: Optional[list[str]] = None,
        viewport: tuple[int, int] = (1280, 720),
        max_actions_per_step: int = 25,
        headless: bool = True,
    ) -> None:
        self.test = test
        self.llm = llm
        self.output_root = Path(output_root)
        self.memories = memories or []
        self.credentials_available = credentials_available or []
        self.viewport = viewport
        self.max_actions_per_step = max_actions_per_step
        self.headless = headless

    async def run(self) -> RunResult:
        run_id = uuid.uuid4().hex[:12]
        output_dir = self.output_root / run_id
        screenshots_dir = output_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        started_at = datetime.now(timezone.utc).isoformat()
        step_results: list[StepResult] = []
        prelude_error: Optional[str] = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                viewport={"width": self.viewport[0], "height": self.viewport[1]},
                record_video_dir=str(output_dir),
                record_video_size={
                    "width": self.viewport[0],
                    "height": self.viewport[1],
                },
            )
            page = await context.new_page()

            # Setup: navigate to projectUrl if present. Failure here is attached
            # to the first step's error as a prelude.
            if self.test.projectUrl:
                try:
                    await page.goto(
                        self.test.projectUrl,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                except Exception as e:
                    prelude_error = f"failed to open projectUrl: {e}"

            for i, step in enumerate(self.test.steps):
                step_started = time.monotonic()
                screenshot_path = screenshots_dir / f"step-{i:02d}.png"

                # Pre-step screenshot — capture into bytes and persist to disk.
                try:
                    screenshot_bytes = await page.screenshot(
                        path=str(screenshot_path), full_page=False
                    )
                    screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
                except Exception as e:
                    screenshot_b64 = ""
                    if prelude_error is None:
                        prelude_error = f"screenshot failed: {e}"

                result = StepResult(
                    step_index=i,
                    type=step.type,
                    title=step.title,
                    status="fail",
                    screenshot_path=str(screenshot_path),
                )

                # If the prelude failed, mark first step failed and stop the run.
                if prelude_error is not None and i == 0:
                    result.error = prelude_error
                    result.duration_ms = int((time.monotonic() - step_started) * 1000)
                    step_results.append(result)
                    # Mark all subsequent steps as skipped.
                    for j, later in enumerate(self.test.steps[i + 1 :], start=i + 1):
                        step_results.append(
                            StepResult(
                                step_index=j,
                                type=later.type,
                                title=later.title,
                                status="skipped",
                            )
                        )
                    break

                dom_summary = await self._build_dom_summary(page)

                ctx = StepContext(
                    step_index=i,
                    step_type=step.type,
                    step_title=step.title,
                    screenshot_b64=screenshot_b64,
                    page_url=page.url,
                    page_title=await self._safe_title(page),
                    dom_summary=dom_summary,
                    memories=self.memories,
                    test_title=self.test.title,
                    project_url=self.test.projectUrl,
                    credentials_available=list(self.credentials_available),
                )

                action_count = 0
                while True:
                    if action_count >= self.max_actions_per_step:
                        result.status = "fail"
                        result.error = "max actions per step exceeded"
                        break

                    action = await self.llm.decide(ctx)
                    action_count += 1

                    record = {
                        "kind": action.kind,
                        "selector": action.selector,
                        "value": action.value,
                        "reasoning": action.reasoning,
                        "success": action.success,
                    }

                    if action.kind == "done":
                        result.status = "pass" if action.success else "fail"
                        if not action.success and not result.error:
                            result.error = action.reasoning or "done with success=False"
                        result.actions.append(record)
                        break

                    if action.kind == "fail":
                        result.status = "fail"
                        result.error = action.reasoning or "agent reported failure"
                        result.actions.append(record)
                        break

                    exec_error = await self._execute_action(action, page)
                    if exec_error is not None:
                        record["error"] = exec_error
                        record["success"] = False
                        result.actions.append(record)
                        result.status = "fail"
                        result.error = exec_error
                        break

                    result.actions.append(record)

                    # Refresh context for the next decide() call: new screenshot,
                    # url, dom.
                    try:
                        shot = await page.screenshot(full_page=False)
                        ctx.screenshot_b64 = base64.b64encode(shot).decode("ascii")
                    except Exception:
                        pass
                    ctx.page_url = page.url
                    ctx.page_title = await self._safe_title(page)
                    ctx.dom_summary = await self._build_dom_summary(page)

                result.duration_ms = int((time.monotonic() - step_started) * 1000)
                step_results.append(result)

            video_obj = page.video
            await context.close()
            await browser.close()

            # Locate the produced video file. Playwright names it with a random
            # GUID; we rename it to video.webm for stability.
            video_path: Optional[str] = None
            try:
                if video_obj is not None:
                    written = await video_obj.path()
                    src = Path(written)
                    dst = output_dir / "video.webm"
                    if src.exists():
                        if dst.exists():
                            dst.unlink()
                        src.rename(dst)
                        video_path = str(dst)
            except Exception:
                video_path = None

            if video_path is None:
                # Fallback: pick the first .webm we find directly in output_dir.
                for candidate in output_dir.glob("*.webm"):
                    if candidate.name == "video.webm":
                        video_path = str(candidate)
                        break
                    dst = output_dir / "video.webm"
                    if dst.exists():
                        dst.unlink()
                    candidate.rename(dst)
                    video_path = str(dst)
                    break

        finished_at = datetime.now(timezone.utc).isoformat()
        overall = "pass" if all(s.status == "pass" for s in step_results) else "fail"

        run_result = RunResult(
            run_id=run_id,
            test_title=self.test.title,
            status=overall,
            output_dir=str(output_dir),
            video_path=video_path,
            steps=step_results,
            started_at=started_at,
            finished_at=finished_at,
        )

        trace_path = output_dir / "trace.json"
        with open(trace_path, "w") as f:
            json.dump(asdict(run_result), f, indent=2, default=str)

        return run_result

    async def _build_dom_summary(self, page: Page) -> str:
        try:
            entries = await page.evaluate(_DOM_SUMMARY_JS)
        except Exception:
            return ""
        if not isinstance(entries, list):
            return ""
        return "\n".join(str(e) for e in entries[:MAX_DOM_ENTRIES])

    async def _safe_title(self, page: Page) -> str:
        try:
            return await page.title()
        except Exception:
            return ""

    async def _execute_action(
        self, action: AgentAction, page: Page
    ) -> Optional[str]:
        """Dispatch an AgentAction against the page. Returns None on success or
        a string error message on failure."""
        try:
            kind = action.kind
            if kind == "navigate":
                if not action.value:
                    return "navigate action missing value"
                await page.goto(
                    action.value, wait_until="domcontentloaded", timeout=30000
                )
            elif kind == "click":
                if not action.selector:
                    return "click action missing selector"
                await page.locator(action.selector).first.click(timeout=10000)
            elif kind == "fill":
                if not action.selector:
                    return "fill action missing selector"
                await page.locator(action.selector).first.fill(
                    action.value or "", timeout=10000
                )
            elif kind == "press":
                if not action.value:
                    return "press action missing value"
                await page.keyboard.press(action.value)
            elif kind == "wait":
                await page.wait_for_timeout(int(action.value or "500"))
            elif kind == "scroll":
                await page.mouse.wheel(0, int(action.value or "500"))
            elif kind == "assert_visible":
                if not action.selector:
                    return "assert_visible missing selector"
                await page.locator(action.selector).first.wait_for(
                    state="visible", timeout=5000
                )
            elif kind == "assert_text":
                if not action.selector:
                    return "assert_text missing selector"
                text = await page.locator(action.selector).first.text_content(
                    timeout=5000
                )
                expected = action.value or ""
                if expected not in (text or ""):
                    return f"assert_text: expected {expected!r} in {text!r}"
            elif kind == "use_credential":
                # MVP: no-op. Credentials are resolved out-of-band.
                return None
            elif kind == "upload_file":
                # MVP: no-op.
                return None
            else:
                return f"unknown action kind: {kind}"
        except Exception as e:
            return f"{type(e).__name__}: {e}"
        return None
