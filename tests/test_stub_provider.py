import pytest

from open_testers.llm import get_provider
from open_testers.llm.base import StepContext


def _ctx(step_index=0, step_type="act", step_title="do", project_url=None):
    return StepContext(
        step_index=step_index,
        step_type=step_type,
        step_title=step_title,
        screenshot_b64="",
        page_url="about:blank",
        page_title="",
        dom_summary="",
        memories=[],
        test_title="t",
        project_url=project_url,
        credentials_available=[],
        extra={},
    )


async def test_act_with_open_intent_navigates_then_done():
    p = get_provider("stub")
    ctx = _ctx(
        step_type="act",
        step_title="Open Hacker News",
        project_url="https://news.ycombinator.com",
    )
    a1 = await p.decide(ctx)
    a2 = await p.decide(ctx)

    assert a1.kind == "navigate"
    assert a1.value == "https://news.ycombinator.com"
    assert a2.kind == "done"
    assert a2.success is True


@pytest.mark.parametrize("step_type", ["screenshot", "assert", "login", "files"])
async def test_other_step_types_done_immediately(step_type):
    p = get_provider("stub")
    a = await p.decide(_ctx(step_type=step_type))
    assert a.kind == "done"
    assert a.success is True


async def test_act_without_navigation_intent_done_immediately():
    p = get_provider("stub")
    a = await p.decide(_ctx(step_type="act", step_title="click the button"))
    assert a.kind == "done"


async def test_act_open_without_project_url_done_immediately():
    p = get_provider("stub")
    a = await p.decide(_ctx(step_type="act", step_title="Open the page", project_url=None))
    # No URL to navigate to → stub falls through to done.
    assert a.kind == "done"
