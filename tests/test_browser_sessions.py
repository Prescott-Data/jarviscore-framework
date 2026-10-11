"""Where the browser subagent works: shared, persistent per person, or fresh."""

import asyncio

import pytest

from jarviscore.kernel.defaults import browser as browser_module
from jarviscore.kernel.defaults.browser import BrowserSubAgent


class _Page:
    def __init__(self, log):
        self.log = log
        self.url = "about:blank"

    async def close(self):
        self.log.append("page.close")


class _Context:
    def __init__(self, log, pages=()):
        self.log = log
        self.pages = list(pages)

    async def new_page(self):
        self.log.append("context.new_page")
        return _Page(self.log)

    async def close(self):
        self.log.append("context.close")


class _Browser:
    def __init__(self, log, contexts=()):
        self.log = log
        self.contexts = list(contexts)

    async def new_context(self, **kwargs):
        self.log.append("browser.new_context")
        return _Context(self.log)

    async def close(self):
        self.log.append("browser.close")


class _Chromium:
    def __init__(self, log, fail=None):
        self.log = log
        self.fail = fail

    async def launch(self, **kwargs):
        self.log.append("launch")
        return _Browser(self.log)

    async def launch_persistent_context(self, user_data_dir, **kwargs):
        if self.fail:
            raise RuntimeError(self.fail)
        self.log.append(("launch_persistent_context", user_data_dir))
        return _Context(self.log, pages=[_Page(self.log)])

    async def connect_over_cdp(self, url):
        self.log.append(("connect_over_cdp", url))
        return _Browser(self.log, contexts=[_Context(self.log)])


class _Playwright:
    def __init__(self, log, fail=None):
        self.chromium = _Chromium(log, fail)
        self.log = log

    async def stop(self):
        self.log.append("playwright.stop")


@pytest.fixture
def log(monkeypatch):
    events = []

    class _Starter:
        async def start(self):
            return _Playwright(events)

    monkeypatch.setattr(browser_module, "PLAYWRIGHT_AVAILABLE", True)
    monkeypatch.setattr(browser_module, "async_playwright", lambda: _Starter(), raising=False)
    return events


def _state(context):
    from types import SimpleNamespace

    return SimpleNamespace(context=context)


def test_each_person_keeps_their_own_profile(tmp_path):
    agent = BrowserSubAgent("b", None, profile_root=str(tmp_path), scope_field="owner_id")

    ada = agent.profile_dir({"owner_id": "ada"})
    bo = agent.profile_dir({"owner_id": "bo"})

    assert ada != bo
    assert ada == agent.profile_dir({"owner_id": "ada"})
    assert ada.startswith(str(tmp_path))


def test_a_step_without_a_person_never_borrows_a_profile(tmp_path):
    agent = BrowserSubAgent("b", None, profile_root=str(tmp_path), scope_field="owner_id")
    assert agent.profile_dir({}) is None


def test_a_hostile_identity_cannot_escape_the_profile_root(tmp_path):
    agent = BrowserSubAgent("b", None, profile_root=str(tmp_path), scope_field="owner_id")
    path = agent.profile_dir({"owner_id": "../../etc"})
    assert path.startswith(str(tmp_path) + "/") and ".." not in path


def test_single_tenant_deployments_share_one_default_profile(tmp_path):
    agent = BrowserSubAgent("b", None, profile_root=str(tmp_path))
    assert agent.profile_dir({}) == agent.profile_dir({"owner_id": "anyone"})


def test_no_profile_root_means_a_fresh_browser():
    assert BrowserSubAgent("b", None).profile_dir({"owner_id": "ada"}) is None


def test_persistent_profile_is_opened_and_closed(log, tmp_path):
    agent = BrowserSubAgent("b", None, profile_root=str(tmp_path), scope_field="owner_id")

    asyncio.run(agent._pre_run_hook(_state({"owner_id": "ada"})))
    assert log[0] == ("launch_persistent_context", agent.profile_dir({"owner_id": "ada"}))
    assert agent._page is not None
    asyncio.run(agent._post_run_hook())

    assert "context.close" in log and "playwright.stop" in log
    assert not browser_module._PROFILE_LOCKS[agent.profile_dir({"owner_id": "ada"})].locked()


def test_shared_browser_is_left_open(log):
    agent = BrowserSubAgent("b", None, control_url="http://127.0.0.1:9222")

    asyncio.run(agent._pre_run_hook(_state({})))
    asyncio.run(agent._post_run_hook())

    assert log[0] == ("connect_over_cdp", "http://127.0.0.1:9222")
    assert "page.close" in log
    assert "context.close" not in log and "browser.close" not in log


def test_launch_failure_is_reported_to_the_agent(log, tmp_path, monkeypatch):
    class _Failing:
        async def start(self):
            return _Playwright(log, fail="profile is in use by another process")

    monkeypatch.setattr(browser_module, "async_playwright", lambda: _Failing(), raising=False)
    agent = BrowserSubAgent("b", None, profile_root=str(tmp_path))

    asyncio.run(agent._pre_run_hook(_state({})))
    result = asyncio.run(agent._tool_navigate("https://example.com"))

    assert result["status"] == "error"
    assert "profile is in use by another process" in result["error"]


def test_one_run_opens_one_browser(log):
    class _LLM:
        async def generate(self, messages=None, **kwargs):
            return {"content": 'THOUGHT: done\nDONE: ok\nRESULT: {"ok": true}', "tokens": {}, "cost_usd": 0.0}

    agent = BrowserSubAgent("b", _LLM())
    asyncio.run(agent.run(task="t", max_turns=1))

    assert log.count("launch") == 1


def _committing_agent(context):
    from types import SimpleNamespace

    agent = BrowserSubAgent("b", None)
    agent._current_state = SimpleNamespace(context=context)
    clicks = []

    async def _click(**params):
        clicks.append(params)
        return {"status": "success"}

    agent._tools["click"].func = _click
    return agent, clicks


ORDER = {"text": "Place order", "irreversible": True, "consequence": "Places the order and charges £29.99"}


def test_an_irreversible_action_waits_for_the_person():
    agent, clicks = _committing_agent({"workflow_id": "wf", "step_id": "buy"})

    result = asyncio.run(agent._execute_tool("click", dict(ORDER)))

    assert result["status"] == "waiting"
    assert result["typed_outcome"] == "WAITING_FOR_APPROVAL"
    assert result["consequence"] == "Places the order and charges £29.99"
    assert len(result["action_id"]) == 64
    assert result["action"] == "Click “Place order” on the current page"
    assert "{" not in result["action"]
    assert clicks == []


def test_an_approval_names_the_element_and_page_a_person_would_recognise():
    target = {"page": "https://shop.test/checkout", "element": {"tag": "BUTTON", "text": "Place order"}}

    action = BrowserSubAgent._describe_action(
        "click", {"selector": "#place-order"}, target, "https://shop.test/basket/add-list?x=1",
    )

    assert action == "Click “Place order” on shop.test/basket/add-list"


def test_the_approved_action_runs_on_resume_and_nothing_else_does():
    context = {"workflow_id": "wf", "step_id": "buy"}
    agent, _ = _committing_agent(context)
    approved = asyncio.run(agent._execute_tool("click", dict(ORDER)))["action_id"]

    resumed, clicks = _committing_agent({**context, "_approved_actions": [approved]})
    assert asyncio.run(resumed._execute_tool("click", dict(ORDER)))["status"] == "success"
    assert clicks == [{"text": "Place order"}]

    other = {**ORDER, "text": "Place order for 10"}
    assert asyncio.run(resumed._execute_tool("click", other))["status"] == "waiting"


def test_an_irreversible_action_must_say_what_it_does():
    agent, clicks = _committing_agent({"workflow_id": "wf", "step_id": "buy"})
    result = asyncio.run(agent._execute_tool("click", {"text": "Place order", "irreversible": True}))
    assert result["semantic_error"] == "CONSEQUENCE_REQUIRED" and clicks == []


@pytest.mark.parametrize("destination, same_action", [
    ("https://shop.test/checkout", True),
    ("https://shop.test/another-order", False),
    (None, False),
])
def test_form_action_identity_survives_alternate_basket_urls(destination, same_action):
    from types import SimpleNamespace

    context = {"workflow_id": "wf", "step_id": "buy"}

    async def identity(page, form):
        agent = BrowserSubAgent("b", None)
        agent._page = SimpleNamespace(url=page)

        async def fingerprint(selector, text):
            return {"tag": "BUTTON", "id": "place-order", "form": form, "method": "post"}

        agent._fingerprint = fingerprint
        target = await agent._action_target("click", {"selector": "#place-order"})
        return agent.action_id(context, "click", target)

    original = asyncio.run(identity("https://shop.test/basket/add-list", "https://shop.test/checkout"))
    resumed = asyncio.run(identity("https://shop.test/basket", destination))

    assert (original == resumed) is same_action


def test_a_resumed_run_is_told_what_the_person_approved():
    from jarviscore.kernel.state import KernelState

    state = KernelState(
        workflow_id="wf", step_id="buy", agent_id="b", task="t",
        context={"workflow_id": "wf", "step_id": "buy"},
    )
    agent, _ = _committing_agent(state.context)
    agent._current_state = state
    waiting = asyncio.run(agent._execute_tool("click", dict(ORDER)))

    unapproved = state.model_copy(deep=True)
    BrowserSubAgent._brief_approval(unapproved)
    assert not any("[APPROVED]" in thought for thought in unapproved.thoughts)

    state.thoughts.extend([
        "Keep this useful observation.",
        "[EPISTEMIC] KNOWLEDGE_PLATEAU: Call DONE with what you have.",
        "[DONE_GATE] Previous completion pressure.",
    ])
    state.output = {"status": "blocked"}
    state.context["_approved_actions"] = [waiting["action_id"]]
    BrowserSubAgent._brief_approval(state)
    briefing = next(thought for thought in state.thoughts if "[APPROVED]" in thought)
    assert "Places the order and charges £29.99" in briefing and '"Place order"' in briefing
    assert "runtime has not executed the action" in briefing
    assert "previous WAITING_FOR_APPROVAL receipt" in briefing
    assert "Verify current provider state first" in briefing
    assert state.output is None
    assert state.thoughts[0] == "Keep this useful observation."
    assert not any("KNOWLEDGE_PLATEAU" in thought or "DONE_GATE" in thought for thought in state.thoughts)
    assert "_pending_approval" not in state.internal_variables


def test_reversible_actions_run_without_asking():
    agent, clicks = _committing_agent({"workflow_id": "wf", "step_id": "buy"})
    assert asyncio.run(agent._execute_tool("click", {"text": "Add to cart"}))["status"] == "success"
    assert clicks == [{"text": "Add to cart"}]


def _state_with(*tools):
    from jarviscore.kernel.state import KernelState

    state = KernelState(workflow_id="wf", step_id="s", agent_id="b", task="t")
    for name, output in tools:
        state.add_tool_result(name, {}, output)
    return state


DONE = {"type": "done", "summary": "Backpack is $29.99, badge shows 1", "result": {"price": "$29.99"}}


@pytest.mark.parametrize("tools", [
    (),
    (("navigate", {"status": "success"}), ("click", {"status": "success"})),
    (("navigate", {"status": "success"}), ("get_text", {"status": "success", "text": "$29.99"})),
])
def test_a_browser_result_completes_with_what_the_run_did_on_record(tools):
    state = _state_with(*tools)
    agent = BrowserSubAgent("b", None)

    assert agent._can_complete(state, DONE) == (True, "")
    assert agent._work_record(state) == {
        name: {"calls": 1, "succeeded": 1} for name, _ in tools
    }


def test_browser_receipts_expose_runtime_observation_timestamps():
    from jarviscore.context.context_manager import ContextManager

    state = _state_with(("get_text", {"status": "success", "text": "Order confirmed"}))
    receipt = state.tool_history[0]

    context = ContextManager().build_context(state)

    assert receipt.receipt_id in context
    assert f"observed at {receipt.observed_at.isoformat()}" in context


def test_an_honest_report_that_the_browser_failed_completes():
    state = _state_with(("navigate", {"status": "error", "error": "net::ERR_NAME_NOT_RESOLVED"}))
    assert BrowserSubAgent("b", None)._can_complete(state, DONE)[0]


BASKET = """<table>
<tr><td>apples-6</td><td><input name="qty" value="4"></td><td>£7.60</td></tr>
<tr><td>milk-2l</td><td><input name="qty" value="1"><input type="hidden" name="sku" value="milk-2l"></td></tr>
</table>
<label>Slot <select><option>Sat 10:00</option><option selected>Sun 10:00</option></select></label>
<label><input type="checkbox" checked> Substitutes</label>"""


def test_the_page_text_shows_what_form_fields_hold():
    async_api = pytest.importorskip("playwright.async_api")

    async def read():
        async with async_api.async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"no Playwright browser: {exc}")
            page = await browser.new_page()
            await page.set_content(BASKET)
            await page.fill("tr:first-child input", "4")
            agent = BrowserSubAgent("b", None)
            agent._page = page
            whole = await agent._tool_get_text()
            row = await agent._tool_get_text(selector="tr:last-child")
            field = await agent._tool_get_text(selector="select")
            await browser.close()
            return whole["text"], row["text"], field["text"]

    whole, row, field = asyncio.run(read())
    assert "[4]" in whole and "[1]" in whole and "[Sun 10:00]" in whole and "[x]" in whole
    assert "milk-2l" in row and "[1]" in row and "hidden" not in row
    assert field == "[Sun 10:00]"
