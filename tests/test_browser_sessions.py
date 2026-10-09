"""Where the browser subagent works: shared, persistent per person, or fresh."""

import asyncio
import json

import pytest

from jarviscore.kernel.defaults import browser as browser_module
from jarviscore.kernel.defaults.browser import BrowserSubAgent


class _Page:
    def __init__(self, log):
        self.log = log
        self.url = "about:blank"
        self.closed = False

    async def close(self):
        self.closed = True
        self.log.append("page.close")

    def is_closed(self):
        return self.closed


class _Session:
    def __init__(self, log):
        self.log = log

    async def send(self, method, params=None):
        self.log.append(("cdp", method, (params or {}).get("userAgent")))
        if method == "Browser.getVersion":
            return {"product": "HeadlessChrome/153.0.7390.54"}
        return {}

    async def detach(self):
        pass


class _Context:
    def __init__(self, log, pages=()):
        self.log = log
        self.pages = list(pages)
        self.page_handlers = []

    async def new_page(self):
        self.log.append("context.new_page")
        return _Page(self.log)

    async def new_cdp_session(self, page):
        return _Session(self.log)

    def on(self, event, handler):
        self.page_handlers.append(handler)

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


def _epochs(monkeypatch, statuses):
    """Run the browser agent once per status, as the base loop would end each run."""
    from types import SimpleNamespace

    from jarviscore.kernel.subagent import BaseSubAgent

    pages = []

    async def base_run(self, task, context=None, max_turns=20, model=None, **kwargs):
        await self._pre_run_hook(_state(context))
        pages.append(self._page)
        return SimpleNamespace(status=statuses.pop(0))

    monkeypatch.setattr(BaseSubAgent, "run", base_run)
    return pages


def test_a_step_continues_on_the_page_its_last_epoch_left(log, monkeypatch):
    pages = _epochs(monkeypatch, ["epoch_exhausted", "success"])
    agent = BrowserSubAgent("b", None)
    step = {"workflow_id": "wf", "step_id": "shop"}

    async def scenario():
        await agent.run("order", dict(step))
        assert log.count("launch") == 1 and "page.close" not in log
        await agent.run("order", {**step, "_resume": True, "_new_execution_epoch": True})

    asyncio.run(scenario())

    assert pages[0] is pages[1]
    assert log.count("launch") == 1
    assert log.count("browser.close") == 1
    assert agent._page is None and agent._held_for is None


def test_another_step_never_inherits_a_held_page(log, monkeypatch):
    pages = _epochs(monkeypatch, ["epoch_exhausted", "success"])
    agent = BrowserSubAgent("b", None)

    async def scenario():
        await agent.run("order", {"workflow_id": "wf", "step_id": "shop"})
        await agent.run("other", {"workflow_id": "wf2", "step_id": "shop",
                                  "_resume": True, "_new_execution_epoch": True})

    asyncio.run(scenario())

    assert pages[0] is not pages[1] and pages[0].closed
    assert log.count("launch") == 2


def test_any_other_ending_closes_the_browser(log, monkeypatch):
    _epochs(monkeypatch, ["yield"])
    agent = BrowserSubAgent("b", None)

    asyncio.run(agent.run("order", {"workflow_id": "wf", "step_id": "shop"}))

    assert "browser.close" in log and agent._page is None and agent._held_for is None


def test_a_continuation_that_never_comes_releases_the_browser(log, monkeypatch):
    _epochs(monkeypatch, ["epoch_exhausted"])
    agent = BrowserSubAgent("b", None)
    agent.continuation_hold_s = 0.05

    async def scenario():
        await agent.run("order", {"workflow_id": "wf", "step_id": "shop"})
        assert agent._page is not None
        await asyncio.sleep(0.2)

    asyncio.run(scenario())

    assert "browser.close" in log and agent._page is None


def test_teardown_closes_a_held_browser(log, monkeypatch):
    _epochs(monkeypatch, ["epoch_exhausted"])
    agent = BrowserSubAgent("b", None)

    async def scenario():
        await agent.run("order", {"workflow_id": "wf", "step_id": "shop"})
        await agent.teardown()

    asyncio.run(scenario())

    assert "browser.close" in log and agent._page is None and agent._hold_expiry is None


def test_no_profile_root_means_a_fresh_browser():
    assert BrowserSubAgent("b", None).profile_dir({"owner_id": "ada"}) is None


def test_persistent_profile_is_opened_and_closed(log, tmp_path):
    agent = BrowserSubAgent("b", None, profile_root=str(tmp_path), scope_field="owner_id")

    asyncio.run(agent._pre_run_hook(_state({"owner_id": "ada"})))
    assert log[0] == ("launch_persistent_context", agent.profile_dir({"owner_id": "ada"}))
    assert agent._page is not None
    overrides = [entry[2] for entry in log if entry[:2] == ("cdp", "Network.setUserAgentOverride")]
    assert overrides and "HeadlessChrome" not in overrides[0] and "Chrome/153.0.0.0" in overrides[0]
    assert len(agent._context.page_handlers) == 1
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


def _committing_agent(context, store=None):
    from types import SimpleNamespace

    from jarviscore.testing.mocks import MockRedisContextStore

    agent = BrowserSubAgent("b", None, redis_store=store or MockRedisContextStore())
    agent._current_state = SimpleNamespace(context=context)
    clicks = []

    async def _click(**params):
        clicks.append(params)
        return {"status": "success", "url": "https://shop.test/orders/FC-1"}

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
    request = agent.redis_store.get_hitl_request("wf", "buy", result["action_id"])
    assert request["status"] == "pending" and request["category"] == "critical_action"
    assert request["action"]["params"] == {"text": "Place order"}
    assert result["hitl_request_id"] == request["request_id"]


def test_an_approval_names_the_element_and_page_a_person_would_recognise():
    target = {"page": "https://shop.test/checkout", "element": {"tag": "BUTTON", "text": "Place order"}}

    action = BrowserSubAgent._describe_action(
        "click", {"selector": "#place-order"}, target, "https://shop.test/basket/add-list?x=1",
    )

    assert action == "Click “Place order” on shop.test/basket/add-list"


def test_only_the_approved_action_runs_and_it_runs_once():
    context = {"workflow_id": "wf", "step_id": "buy"}
    agent, clicks = _committing_agent(context)
    approved = asyncio.run(agent._execute_tool("click", dict(ORDER)))["action_id"]
    agent.redis_store.resolve_hitl_request("wf", "buy", "approve", action_id=approved)

    assert asyncio.run(agent._execute_tool("click", dict(ORDER)))["status"] == "success"
    again = asyncio.run(agent._execute_tool("click", dict(ORDER)))
    assert clicks == [{"text": "Place order"}]
    assert again["url"] == "https://shop.test/orders/FC-1" and "already ran" in again["note"]

    other = {**ORDER, "text": "Place order for 10"}
    assert asyncio.run(agent._execute_tool("click", other))["status"] == "waiting"


def test_an_approved_action_the_page_blocked_stays_approved_until_it_runs():
    context = {"workflow_id": "wf", "step_id": "buy"}
    agent, clicks = _committing_agent(context)
    approved = asyncio.run(agent._execute_tool("click", dict(ORDER)))["action_id"]
    agent.redis_store.resolve_hitl_request("wf", "buy", "approve", action_id=approved)
    real_click = agent._tools["click"].func

    async def covered(**params):
        return {"status": "error", "error": "Element e53 is covered by a cookie dialog.",
                "semantic_error": "ELEMENT_NOT_ACTIONABLE", "performed": False}

    agent._tools["click"].func = covered
    blocked = asyncio.run(agent._execute_tool("click", dict(ORDER)))
    agent._tools["click"].func = real_click
    placed = asyncio.run(agent._execute_tool("click", dict(ORDER)))
    again = asyncio.run(agent._execute_tool("click", dict(ORDER)))

    assert blocked["semantic_error"] == "ELEMENT_NOT_ACTIONABLE" and "note" not in blocked
    assert placed["status"] == "success" and clicks == [{"text": "Place order"}]
    assert "already ran" in again["note"]


def test_a_declined_action_is_never_performed():
    agent, clicks = _committing_agent({"workflow_id": "wf", "step_id": "buy"})
    declined = asyncio.run(agent._execute_tool("click", dict(ORDER)))["action_id"]
    agent.redis_store.resolve_hitl_request("wf", "buy", "reject", action_id=declined)

    result = asyncio.run(agent._execute_tool("click", dict(ORDER)))

    assert result["semantic_error"] == "ACTION_DECLINED" and clicks == []


def test_without_durable_state_no_one_can_approve_so_nothing_runs():
    from types import SimpleNamespace

    agent = BrowserSubAgent("b", None)
    agent._current_state = SimpleNamespace(context={"workflow_id": "wf", "step_id": "buy"})
    result = asyncio.run(agent._execute_tool("click", dict(ORDER)))
    assert result["semantic_error"] == "APPROVAL_UNAVAILABLE"


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

        async def fingerprint(selector, text="", ref=""):
            return {"tag": "BUTTON", "id": "place-order", "form": form, "method": "post"}

        agent._fingerprint = fingerprint
        target = await agent._action_target("click", {"selector": "#place-order"})
        return agent.action_id(context, "click", target)

    original = asyncio.run(identity("https://shop.test/basket/add-list", "https://shop.test/checkout"))
    resumed = asyncio.run(identity("https://shop.test/basket", destination))

    assert (original == resumed) is same_action


def test_an_order_for_another_delivery_slot_is_a_different_decision():
    from types import SimpleNamespace

    context = {"workflow_id": "wf", "step_id": "buy"}

    async def identity(slot):
        agent = BrowserSubAgent("b", None)
        agent._page = SimpleNamespace(url="https://shop.test/checkout")

        async def fingerprint(selector, text="", ref=""):
            return {"tag": "BUTTON", "text": "Place order", "form": "https://shop.test/checkout",
                    "method": "post", "fields": [["slot", slot]]}

        agent._fingerprint = fingerprint
        return agent.action_id(context, "click", await agent._action_target("click", {"text": "Place order"}))

    wednesday = asyncio.run(identity("2026-10-14T10:00"))

    assert wednesday == asyncio.run(identity("2026-10-14T10:00"))
    assert wednesday != asyncio.run(identity("2026-10-10T10:00"))


def _resumed_after(decision, applies=True):
    from jarviscore.kernel.state import KernelState
    from jarviscore.kernel.tracing import create_noop_trace
    from jarviscore.testing.mocks import MockRedisContextStore

    store = MockRedisContextStore()
    state = KernelState(
        workflow_id="wf", step_id="buy", agent_id="b", task="t",
        context={"workflow_id": "wf", "step_id": "buy"},
    )
    agent, clicks = _committing_agent(state.context, store)
    agent._current_state = state
    waiting = asyncio.run(agent._execute_tool("click", dict(ORDER)))
    store.resolve_hitl_request("wf", "buy", decision, action_id=waiting["action_id"])
    state.output = {"status": "blocked"}
    state.thoughts.extend([
        "Keep this useful observation.",
        "[DONE_GATE] Previous completion pressure.",
    ])

    async def still_applies(action):
        return applies

    agent._approved_action_applies = still_applies
    asyncio.run(agent._carry_out_decided_actions(state, create_noop_trace()))
    asyncio.run(agent._carry_out_decided_actions(state, create_noop_trace()))
    outcome = store.get_hitl_request("wf", "buy", waiting["action_id"])["outcome"]
    return state, clicks, outcome


def test_a_resumed_step_performs_the_approved_action_once_with_a_receipt():
    state, clicks, outcome = _resumed_after("approve")

    assert clicks == [{"text": "Place order"}]
    assert [t.tool_name for t in state.tool_history] == ["click"]
    assert state.tool_history[0].status == "success"
    performed = [t for t in state.thoughts if t.startswith("[HITL APPROVED, PERFORMED]")]
    assert len(performed) == 1 and "FC-1" in performed[0]
    assert outcome["status"] == "success"
    assert state.output is None
    assert "Keep this useful observation." in state.thoughts
    assert not any(t.startswith("[DONE_GATE]") for t in state.thoughts)


def test_a_resumed_step_reports_a_declined_action_and_never_runs_it():
    state, clicks, outcome = _resumed_after("reject")

    assert clicks == [] and state.tool_history == []
    assert sum(t.startswith("[HITL DECLINED]") for t in state.thoughts) == 1
    assert outcome == {"status": "declined"}


def test_an_approval_does_not_run_against_a_page_that_changed():
    state, clicks, outcome = _resumed_after("approve", applies=False)

    assert clicks == []
    assert any(t.startswith("[HITL APPROVED, NOT PERFORMED]") for t in state.thoughts)
    assert outcome["status"] == "not_performed"


def test_a_resumed_approval_the_page_blocked_is_left_for_the_agent_to_carry_out():
    from jarviscore.kernel.state import KernelState
    from jarviscore.kernel.tracing import create_noop_trace
    from jarviscore.testing.mocks import MockRedisContextStore

    store = MockRedisContextStore()
    state = KernelState(workflow_id="wf", step_id="buy", agent_id="b", task="t",
                        context={"workflow_id": "wf", "step_id": "buy"})
    agent, clicks = _committing_agent(state.context, store)
    agent._current_state = state
    waiting = asyncio.run(agent._execute_tool("click", dict(ORDER)))
    store.resolve_hitl_request("wf", "buy", "approve", action_id=waiting["action_id"])

    async def covered(**params):
        return {"status": "error", "error": "covered by a cookie dialog",
                "semantic_error": "ELEMENT_NOT_ACTIONABLE", "performed": False}

    async def still_applies(action):
        return True

    agent._tools["click"].func = covered
    agent._approved_action_applies = still_applies
    asyncio.run(agent._carry_out_decided_actions(state, create_noop_trace()))

    assert store.get_hitl_request("wf", "buy", waiting["action_id"]).get("outcome") is None
    assert any(t.startswith("[HITL APPROVED, NOT YET PERFORMED]") for t in state.thoughts)
    assert not any(t.startswith("[HITL APPROVED, PERFORMED]") for t in state.thoughts)


def test_an_approval_that_could_not_be_performed_is_asked_again_fresh():
    from jarviscore.contracts.hitl import HITLAction
    from jarviscore.kernel import approval as approval_module
    from jarviscore.testing.mocks import MockRedisContextStore

    store = MockRedisContextStore()
    action = HITLAction(action_id="a" * 64, tool="click", consequence="Places the order")
    approval_module.gate(store, "wf", "buy", action)
    store.resolve_hitl_request("wf", "buy", "approve", action_id=action.action_id)
    approval_module.settle(store, "wf", "buy", action.action_id, {"status": "not_performed"})

    again = approval_module.gate(store, "wf", "buy", action)
    record = store.get_hitl_request("wf", "buy", action.action_id)

    assert again["typed_outcome"] == "WAITING_FOR_APPROVAL"
    assert record["status"] == "pending" and "decision" not in record and "outcome" not in record


def test_an_action_proposed_by_ref_is_found_again_by_what_it_touches():
    from types import SimpleNamespace

    from jarviscore.contracts.hitl import HITLAction

    button = {"tag": "BUTTON", "id": "place-order", "text": "Place order", "form": None}
    elements_after_reload = {"e7": {"tag": "A", "text": "Basket"}, "e45": button}

    class _Page:
        url = "http://shop.test/basket"

        async def goto(self, url, wait_until=None):
            return None

    agent = BrowserSubAgent("b", None)
    agent._page = _Page()
    agent._current_state = SimpleNamespace(context={"workflow_id": "wf", "step_id": "buy"})

    async def index():
        return [{"ref": ref, "role": "button", "name": "", "state": ""} for ref in elements_after_reload]

    async def fingerprint(selector="", text="", ref=""):
        return {"f1e45": button}.get(ref) or elements_after_reload.get(ref)

    agent._index = index
    agent._fingerprint = fingerprint
    proposed = asyncio.run(agent._action_target("click", {"ref": "f1e45"}))
    action = HITLAction(
        action_id=agent.action_id(agent._current_state.context, "click", proposed),
        tool="click", params={"ref": "f1e45"}, consequence="Places the order",
        location="http://shop.test/basket",
    )

    assert asyncio.run(agent._approved_action_applies(action)) is True
    assert agent._approved_action_params(action)["ref"] == "e45"


def test_reversible_actions_run_without_asking():
    agent, clicks = _committing_agent({"workflow_id": "wf", "step_id": "buy"})
    assert asyncio.run(agent._execute_tool("click", {"text": "Add to cart"}))["status"] == "success"
    assert clicks == [{"text": "Add to cart"}]


def test_the_browser_presents_the_chrome_that_is_running():
    identity = browser_module.browser_identity("153.0.7390.54", system="Darwin", machine="arm64")

    assert identity["userAgent"] == (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    )
    metadata = identity["userAgentMetadata"]
    assert metadata["platform"] == "macOS" and metadata["architecture"] == "arm"
    assert {"brand": "Google Chrome", "version": "153.0.7390.54"} in metadata["fullVersionList"]
    assert "Headless" not in json.dumps(identity)


SNAPSHOT = """\
- generic [active] [ref=f7e1]:
  - banner [ref=f7e2]:
    - link "FreshCart" [ref=f7e3] [cursor=pointer]:
      - /url: /
  - combobox [disabled] [aria-hidden] [ref=f7e9]
  - combobox "Departing from" [ref=f7e10]
  - heading "Basket" [level=2] [ref=f7e11]
  - paragraph [ref=f7e20]:
    - text: "One product per line:"
    - code [ref=f7e21]: SKU quantity
  - table [ref=f7e22]:
    - rowgroup [ref=f7e23]:
      - row "SKU Product" [ref=f7e24]:
        - columnheader "SKU" [ref=f7e25]
        - columnheader "Product" [ref=f7e26]
      - row "rice-1kg Basmati rice 1kg" [ref=f7e27]:
        - cell "rice-1kg" [ref=f7e28]
        - cell "Basmati rice 1kg" [ref=f7e29]
  - 'link "Delivery: this week - see slots" [ref=f7e30] [cursor=pointer]':
    - /url: /slots
    - generic [ref=f7e31]: "Delivery: this week"
    - generic [ref=f7e32]: see slots
  - button "Place \\"express\\" order" [ref=f7e12] [cursor=pointer]
"""


class _SnapshotPage:
    url = "https://shop.test/basket"

    def __init__(self, disabled=()):
        self.disabled = set(disabled)
        self.clicked = []

    def locator(self, selector):
        return _SnapshotLocator(self, selector)

    async def title(self):
        return "Basket"

    async def wait_for_load_state(self, state, timeout=None):
        return None


class _SnapshotLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    async def aria_snapshot(self, mode=None):
        return SNAPSHOT

    async def count(self):
        return 1

    async def is_disabled(self):
        return self.selector.removeprefix("aria-ref=") in self.page.disabled

    async def is_visible(self):
        return True

    async def scroll_into_view_if_needed(self, timeout=None):
        return None

    async def evaluate(self, script, *args, **kwargs):
        return None

    async def click(self, timeout=None):
        self.page.clicked.append(self.selector.removeprefix("aria-ref="))


class _Decisions:
    """A decision model answering from fixed tables, recording what it was asked."""

    def __init__(self, choice="f7e10", confidence=0.9, commits=0.05, denied=0.02):
        self.choice, self.confidence, self.commits, self.denied = choice, confidence, commits, denied
        self.asked = []

    async def evaluate(self, state, questions, model=None):
        from types import SimpleNamespace

        self.asked.append(questions)
        answers = {}
        for name, question in questions.items():
            if question["type"] == "choice":
                self.criteria = question["criteria"]
                answers[name] = {"choice": self.choice, "confidence": self.confidence,
                                 "probabilities": {self.choice: self.confidence}}
            else:
                answers[name] = {"noul": self.commits if name == "commits" else self.denied}
        return SimpleNamespace(request_id="req-1", answers=answers)

    async def close(self):
        return None


def _indexed_agent(disabled=()):
    agent = BrowserSubAgent("b", None)
    agent._page = _SnapshotPage(disabled)
    return agent


def test_the_snapshot_reads_the_page_as_a_person_sees_it():
    result = asyncio.run(_indexed_agent()._tool_snapshot())

    assert result["page"].splitlines() == [
        '[f7e3] link "FreshCart"',
        "[f7e9] combobox (disabled aria-hidden)",
        '[f7e10] combobox "Departing from"',
        "## Basket",
        "One product per line: SKU quantity",
        "| SKU | Product |",
        "| rice-1kg | Basmati rice 1kg |",
        '[f7e30] link "Delivery: this week - see slots"',
        '[f7e12] button "Place "express" order"',
    ]


def test_the_index_lists_only_what_can_be_acted_on():
    elements = asyncio.run(_indexed_agent()._index())

    assert [(e["ref"], e["role"], e["name"], e["state"]) for e in elements] == [
        ("f7e3", "link", "FreshCart", ""),
        ("f7e9", "combobox", "", "disabled aria-hidden"),
        ("f7e10", "combobox", "Departing from", ""),
        ("f7e12", "button", 'Place "express" order', ""),
    ]


def test_a_disabled_element_is_refused_at_once_with_the_reason():
    result = asyncio.run(_indexed_agent(disabled={"f7e9"})._tool_click(ref="f7e9"))

    assert result["semantic_error"] == "ELEMENT_NOT_ACTIONABLE"
    assert "disabled" in result["error"]


def test_find_asks_the_decision_model_and_returns_its_evidence():
    class _Decisions:
        async def evaluate(self, state, questions):
            from types import SimpleNamespace

            self.criteria = questions["element"]["criteria"]
            return SimpleNamespace(request_id="req-1", answers={"element": {
                "choice": "f7e10", "confidence": 0.82,
                "probabilities": {"f7e10": 0.82, "f7e12": 0.1, "f7e3": 0.08},
            }})

    agent = _indexed_agent()
    agent.decision_client = _Decisions()
    result = asyncio.run(agent._tool_find("Enter the departure station"))

    assert result["ref"] == "f7e10" and result["confidence"] == 0.82
    assert result["element"]["name"] == "Departing from"
    assert [a["ref"] for a in result["alternatives"]] == ["f7e12", "f7e3"]
    assert "f7e9" not in agent.decision_client.criteria


def _acting_agent(**decisions):
    agent = _indexed_agent()
    agent.decision_client = _Decisions(**decisions)
    agent.redis_store = None
    return agent


def test_act_finds_and_clicks_in_one_step_when_the_choice_is_clear():
    agent = _acting_agent(choice="f7e3", confidence=0.95)

    result = asyncio.run(agent._execute_tool("act", {"goal": "Go to the shop home", "action": "click"}))

    assert result["status"] == "success" and agent._page.clicked == ["f7e3"]
    assert result["acted_on"]["name"] == "FreshCart" and result["confidence"] == 0.95


def test_a_page_an_action_reaches_counts_as_progress():
    from types import SimpleNamespace

    agent = _acting_agent(choice="f7e3", confidence=0.95)
    agent._current_state = SimpleNamespace(internal_variables={})

    asyncio.run(agent._execute_tool("click", {"ref": "f7e3"}))
    asyncio.run(agent._execute_tool("click", {"ref": "f7e9"}))

    assert len(agent._current_state.internal_variables["_observed_states"]) == 1


def test_act_hands_back_the_choice_when_the_model_is_unsure():
    agent = _acting_agent(choice="f7e3", confidence=0.4)

    result = asyncio.run(agent._tool_act("Go to the shop home"))

    assert result["status"] == "needs_choice" and agent._page.clicked == []
    assert result["candidates"][0]["ref"] == "f7e3"


def test_act_never_performs_a_consequential_action():
    agent = _acting_agent(choice="f7e12", confidence=0.99, commits=0.97)

    result = asyncio.run(agent._tool_act("Finish the purchase"))
    flagged = asyncio.run(agent._execute_tool(
        "act", {"goal": "Finish the purchase", "irreversible": True, "consequence": "Pays"},
    ))

    assert result["semantic_error"] == "CONSEQUENTIAL_ACTION" and result["ref"] == "f7e12"
    assert flagged["semantic_error"] == "IRREVERSIBLE_NEEDS_EXACT_ELEMENT"
    assert agent._page.clicked == []


def test_navigation_reports_whether_the_site_turned_the_browser_away():
    class _Response:
        status = 403

    class _Page(_SnapshotPage):
        async def goto(self, url, wait_until=None, timeout=None):
            self.url = url
            return _Response()

        async def evaluate(self, script):
            return "Access Denied. Reference #18.2f"

    agent = BrowserSubAgent("b", None)
    agent._page = _Page()
    agent.site_interval_s = 0
    agent.decision_client = _Decisions(denied=0.97)

    result = asyncio.run(agent._tool_navigate("https://shop.test/search"))

    assert result["access"] == {"denied": True, "probability": 0.97, "decision_request_id": "req-1"}
    assert result["http_status"] == 403


def test_requests_to_one_site_are_spaced():
    import time

    agent = BrowserSubAgent("b", None)
    agent.site_interval_s = 0.2
    browser_module._LAST_VISIT.clear()

    async def two_visits():
        await agent._pace("https://shop.test/a")
        started = time.monotonic()
        await agent._pace("https://shop.test/b")
        same_site = time.monotonic() - started
        started = time.monotonic()
        await agent._pace("https://other.test/a")
        return same_site, time.monotonic() - started

    same_site, other_site = asyncio.run(two_visits())

    assert same_site >= 0.18 and other_site < 0.05


def test_any_decision_model_can_be_plugged_in(monkeypatch):
    import sys
    import types

    from jarviscore.execution.decisions import (
        DecisionClient,
        DecisionClientError,
        create_decision_client,
    )

    module = types.ModuleType("my_decisions")
    module.make = lambda config: _Decisions()
    module.broken = lambda config: object()
    monkeypatch.setitem(sys.modules, "my_decisions", module)

    client = create_decision_client({"decision_client_factory": "my_decisions:make"})

    assert isinstance(client, DecisionClient) and isinstance(client, _Decisions)
    with pytest.raises(DecisionClientError, match="did not return a DecisionClient"):
        create_decision_client({"decision_client_factory": "my_decisions:broken"})


def test_perception_is_observed_whole():
    from jarviscore.kernel.subagent import _observe

    index = "x" * 5000

    assert _observe("snapshot", index, 1, "snapshot" in BrowserSubAgent.whole_observation_tools) == index
    assert len(_observe("get_text", index, 1)) < 1200


def test_only_the_latest_snapshot_stays_in_view():
    from jarviscore.kernel.subagent import _thread_history

    def turn(n, perception):
        return {"assistant": f"a{n}", "observation": f"page {n}", "perception": perception,
                "superseded": f"turn {n} replaced; read_turn_result {n}"}

    messages = []
    _thread_history(messages, [turn(1, True), turn(2, False), turn(3, True)])
    shown = [m["content"] for m in messages if m["role"] == "user"]

    assert shown == ["turn 1 replaced; read_turn_result 1", "page 2", "page 3"]


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
])
def test_a_result_the_page_never_showed_cannot_complete(tools):
    ok, evidence = BrowserSubAgent("b", None)._can_complete(_state_with(*tools), DONE)
    assert not ok and evidence.check == "browser_observation"


def test_a_result_read_from_the_page_completes():
    state = _state_with(("navigate", {"status": "success"}), ("get_text", {"status": "success", "text": "$29.99"}))
    assert BrowserSubAgent("b", None)._can_complete(state, DONE) == (True, None)


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
