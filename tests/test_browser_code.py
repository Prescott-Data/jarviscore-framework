"""run_playwright: the agent's Playwright code, confined, against its live page."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarviscore.kernel.defaults import browser as browser_module
from jarviscore.kernel.defaults.browser import BrowserSubAgent
from jarviscore.kernel.subagent import _observe

async_api = pytest.importorskip("playwright.async_api")

RUNS = """<h1>Runs page 1</h1>
<table><tr><th>Sync</th><th>Status</th></tr>
<tr><td>Clicks</td><td>error</td></tr><tr><td>Views</td><td>ok</td></tr></table>
<button onclick="document.querySelector('h1').innerText='Runs page 2'">Next</button>
<label>Search <input id=q onkeydown="if (event.key==='Enter') document.body.dataset.searched=this.value"></label>
<form onsubmit="event.preventDefault(); document.body.dataset.paid='yes'">
<button id=pay type=submit>Pay £40 now</button></form>"""


class _Judge:
    """Commits for anything that pays; records what it was asked."""

    def __init__(self, fail=False):
        self.asked, self.fail = [], fail

    async def evaluate(self, state, questions):
        if self.fail:
            raise RuntimeError("decision model unavailable")
        self.asked.append(state)
        commits = 0.95 if "Pay" in state else 0.02
        return SimpleNamespace(request_id="r", answers={"commits": {"noul": commits}})


def _run(code, html=RUNS, judge=None, timeout_s=60, after=None):
    from jarviscore.execution.isolation import confinement_unavailable_reason

    async def go():
        async with async_api.async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"no Playwright browser: {exc}")
            page = await browser.new_page()
            await page.set_content(html)
            agent = BrowserSubAgent(
                "b", None, allow_unsafe_local_execution=confinement_unavailable_reason() is not None,
            )
            agent._page = page
            agent.site_interval_s = 0
            agent.decision_client = judge or _Judge()
            try:
                result = await agent._run_playwright(code, timeout_s=timeout_s)
                seen = await page.evaluate(after) if after else None
            finally:
                await agent.teardown()
                await browser.close()
            return result, seen

    return asyncio.run(go())


def test_code_reads_and_pages_through_the_live_page_and_returns_what_it_found():
    result, _ = _run(
        'rows = await page.locator("tr").all_inner_texts()\n'
        'await page.get_by_role("button", name="Next").click()\n'
        'print("read", len(rows))\n'
        'result = {"rows": rows, "heading": await page.locator("h1").inner_text(),\n'
        '          "error": "INVALID_CUSTOMER is page data"}\n'
    )

    assert result["status"] == "success"
    assert result["result"] == {
        "rows": ["Sync\tStatus", "Clicks\terror", "Views\tok"],
        "heading": "Runs page 2",
        "error": "INVALID_CUSTOMER is page data",
    }
    assert result["stdout"] == "read 3\n"
    assert [a["action"] for a in result["actions"]] == ["click"]
    assert "page" not in result


def test_code_variables_survive_between_calls():
    async def exercise():
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            agent = BrowserSubAgent("b", None)
            agent._page = await browser.new_page()
            agent.decision_client = _Judge()
            await agent._page.set_content(RUNS)
            try:
                first = await agent._run_playwright(
                    'rows = page.locator("tr")\n'
                    'inventory = await rows.all_inner_texts()\n'
                    'state["inventory"] = inventory\n'
                    'def count_inventory():\n    return len(inventory)\n'
                    'result = count_inventory()'
                )
                second = await agent._run_playwright(
                    'result = {"count": count_inventory(), "current": await rows.count()}'
                )
                assert first["result"] == 3
                assert second["status"] == "success", second.get("error")
                assert second["result"] == {"count": 3, "current": 3}
                assert agent._browser_findings["inventory"] == ["Sync\tStatus", "Clicks\terror", "Views\tok"]
                assert second["state_keys"] == ["inventory"]
                failed = await agent._run_playwright('raise ValueError("bad cell")')
                assert failed["status"] == "error"
                recovered = await agent._run_playwright('result = count_inventory()')
                assert recovered["result"] == 3
                process = agent._code_sandbox._browser_process
            finally:
                await agent.teardown()
                await browser.close()
            assert process.returncode is not None

    asyncio.run(exercise())


def test_browser_runtime_round_trips_through_a_checkpoint():
    from jarviscore.kernel.state import KernelState

    first = BrowserSubAgent("b", None)
    first._browser_findings = {"inventory": ["a", "b"], "unfinished": ["b"]}
    first._programs = [{"code": "state['inventory'] = ['a', 'b']", "wrote": ["inventory"]}]
    first._current_url = "https://app.data.test/history"
    state = KernelState(workflow_id="wf", step_id="inspect", agent_id="b")
    first._save_subagent_state(state)
    restored = KernelState.model_validate_json(state.model_dump_json())
    second = BrowserSubAgent("b", None)
    second._restore_subagent_state(restored)
    assert second._browser_findings == first._browser_findings
    assert second._programs == first._programs
    assert second._current_url == first._current_url


def test_browser_code_default_timeout_uses_configuration_and_remaining_lease():
    from jarviscore.kernel.lease import ExecutionLease

    async def go():
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            agent = BrowserSubAgent("b", None)
            agent._page = await browser.new_page()
            agent.code_timeout_s = 410
            timeouts = []

            async def execute(code, *, context, timeout):
                timeouts.append(timeout)
                return {"status": "success", "data": None, "browser_state": {}}

            agent._sandbox_for_code = lambda: SimpleNamespace(execute=execute)
            try:
                await agent._run_playwright("result = 1")
                agent._cognition = SimpleNamespace(lease=ExecutionLease(wall_clock_ms=45_000))
                await agent._run_playwright("result = 1")
                return timeouts
            finally:
                await agent.teardown()
                await browser.close()

    timeouts = asyncio.run(go())
    assert timeouts[0] == 410 + browser_module._CODE_DEADLINE_GRACE_S
    assert 40 + browser_module._CODE_DEADLINE_GRACE_S < timeouts[1] <= 45 + browser_module._CODE_DEADLINE_GRACE_S


def test_a_program_past_its_deadline_keeps_what_it_read():
    async def exercise():
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            agent = BrowserSubAgent("b", None)
            agent._page = await browser.new_page()
            agent.decision_client = _Judge()
            await agent._page.set_content(RUNS)
            try:
                ready = await agent._run_playwright('result = await page.locator("tr").count()')
                assert ready["status"] == "success", ready
                started = time.monotonic()
                cut = await agent._run_playwright(
                    'seen = []\n'
                    'while True:\n'
                    '    seen.append(await page.locator("tr").count())\n'
                    '    state["reads"] = len(seen)\n',
                    timeout_s=2,
                )
                took = time.monotonic() - started
                after = await agent._run_playwright('result = {"seen": len(seen) > 0, "state": state["reads"]}')
            finally:
                await agent.teardown()
                await browser.close()
            assert cut["status"] == "error" and "time is up" in cut["error"]
            assert not cut.get("session_reset")
            assert took < 10
            assert after["status"] == "success", after
            assert after["result"]["seen"] and after["result"]["state"] > 0

    asyncio.run(exercise())


def test_code_observes_the_rendered_result_of_an_action():
        html = '''<h1>Initial</h1><button onclick="document.querySelector('h1').textContent='Loading';
            setTimeout(() => document.querySelector('h1').textContent='Ready', 200)">Next</button>'''
        result, _ = _run(
                'await page.get_by_role("button", name="Next").click()\n'
                'result = await page.locator("h1").inner_text()', html=html,
        )
        assert result["result"] == "Ready"


def test_code_waits_for_the_sites_data_but_not_third_party_beacons():
    html = '''<h1>Loading</h1><button onclick="fetch('https://beacon.tracker.test/rum', {method: 'POST'});
      fetch('https://api.data.test/runs').then(r => r.text())
      .then(t => document.querySelector('h1').textContent = t)">Next</button>'''

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def slow(route):
                await asyncio.sleep(1.5)
                await route.fulfill(body="3 runs", headers={"Access-Control-Allow-Origin": "*"})

            async def beacon(route):
                try:
                    await asyncio.sleep(30)
                    await route.abort()
                except Exception:
                    pass

            await page.route("https://app.data.test/**", lambda route: route.fulfill(body=html, content_type="text/html"))
            await page.route("https://api.data.test/**", slow)
            await page.route("https://beacon.tracker.test/**", beacon)
            await page.goto("https://app.data.test/")
            agent = BrowserSubAgent("b", None)
            agent._page = page
            agent._watch_requests(page)
            agent.decision_client = _Judge()
            started = time.monotonic()
            try:
                out = await agent._run_playwright(
                    'await page.get_by_role("button", name="Next").click()\n'
                    'result = await page.locator("h1").inner_text()'
                )
                return out, time.monotonic() - started
            finally:
                await agent.teardown()
                await browser.close()

    out, took = asyncio.run(go())
    assert out["result"] == "3 runs"
    assert took < 8


def test_a_large_page_reading_reaches_the_agent_whole():
    rows = "".join(f"<p>run {i} failed at 0{i % 10}:00</p>" for i in range(20000))
    result, _ = _run(
        'text = await page.locator("body").inner_text()\n'
        'print(text)\n'
        'result = text',
        html=rows,
    )
    observed = _observe("run_playwright", result, 1)
    assert result["result"].count("failed at") == 20000
    assert result["stdout"].count("failed at") == 20000
    assert "run 19999 failed at 09:00" in observed


def test_code_guidance_is_given_only_with_the_code_tool():
    agent = BrowserSubAgent("b", None)
    agent._tools.setdefault("run_playwright", agent._tools["navigate"])
    assert "## Working In Code" in agent.get_system_prompt()
    del agent._tools["run_playwright"]
    prompt = agent.get_system_prompt()
    assert "## Working In Code" not in prompt and "{code}" not in prompt


def test_code_asking_for_network_idle_on_a_polling_app_reads_its_data():
    html = '''<h1>Loading</h1><script>
      fetch('https://api.data.test/runs').then(r => r.text())
        .then(t => document.querySelector('h1').textContent = t);
      setInterval(() => fetch('https://api.data.test/poll'), 200);
    </script>'''

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def runs(route):
                await asyncio.sleep(1)
                await route.fulfill(body="3 runs", headers={"Access-Control-Allow-Origin": "*"})

            await page.route("https://app.data.test/**", lambda route: route.fulfill(body=html, content_type="text/html"))
            await page.route("https://api.data.test/runs", runs)
            await page.route("https://api.data.test/poll", lambda route: route.fulfill(
                body="ok", headers={"Access-Control-Allow-Origin": "*"}))
            agent = BrowserSubAgent("b", None)
            agent._page = page
            agent._watch_requests(page)
            agent.site_interval_s = 0
            agent.data_timeout_ms = 3000
            agent.decision_client = _Judge()
            started = time.monotonic()
            try:
                out = await agent._run_playwright(
                    'await page.goto("https://app.data.test/", wait_until="networkidle", timeout=20000)\n'
                    'await page.wait_for_load_state("networkidle")\n'
                    'result = await page.locator("h1").inner_text()'
                )
                return out, time.monotonic() - started
            finally:
                await agent.teardown()
                await browser.close()

    out, took = asyncio.run(go())
    assert out["result"] == "3 runs"
    assert took < 15


def test_requests_abandoned_by_a_new_document_are_not_awaited():
    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def never(route):
                try:
                    await asyncio.sleep(30)
                    await route.abort()
                except Exception:
                    pass

            await page.route("https://app.data.test/a", lambda route: route.fulfill(
                body="<script>fetch('https://api.data.test/slow')</script><h1>A</h1>", content_type="text/html"))
            await page.route("https://app.data.test/b", lambda route: route.fulfill(
                body="<h1>B</h1>", content_type="text/html"))
            await page.route("https://api.data.test/**", never)
            agent = BrowserSubAgent("b", None)
            agent._page = page
            agent._watch_requests(page)
            await page.goto("https://app.data.test/a")
            await page.goto("https://app.data.test/b")
            started = time.monotonic()
            await agent._data_quiet()
            took = time.monotonic() - started
            await browser.close()
            return took

    assert asyncio.run(go()) < 3


def test_code_reads_many_pages_at_once_in_its_session():
    from jarviscore.execution.isolation import confinement_unavailable_reason

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            async def item(route):
                await asyncio.sleep(1)
                name = route.request.url.rsplit("/", 1)[1]
                await route.fulfill(body=f"<main>sync {name} failed</main>", content_type="text/html")

            await context.route("https://app.data.test/syncs/**", item)
            page = await context.new_page()
            agent = BrowserSubAgent(
                "b", None, allow_unsafe_local_execution=confinement_unavailable_reason() is not None,
            )
            agent._context, agent._page = context, page
            agent.site_interval_s = 0
            agent.decision_client = _Judge()
            try:
                out = await agent._run_playwright(
                    'import time\n'
                    'urls = [f"https://app.data.test/syncs/{i}" for i in range(4)]\n'
                    'started = time.monotonic()\n'
                    'state["syncs"] = await read_pages(urls, "() => document.querySelector(\'main\').innerText")\n'
                    'result = {"values": [r["value"] for r in state["syncs"]], "seconds": time.monotonic() - started}'
                )
                return out, len(context.pages)
            finally:
                await agent.teardown()
                await browser.close()

    out, open_pages = asyncio.run(go())
    assert out["result"]["values"] == [f"sync {i} failed" for i in range(4)]
    assert out["result"]["seconds"] < 3  # four one-second pages read together, not one after another
    assert open_pages == 1  # the pages it opened are closed again
    assert "syncs" in out["state_keys"]


def test_code_reads_each_paged_history_back_to_the_start_of_the_period():
    from jarviscore.execution.isolation import confinement_unavailable_reason

    def history(sync: str, page: int, last: int) -> str:
        day = "Yesterday" if page == last else "Today"
        rows = "".join(f"<tr><td>{day} run {sync}.{page}.{i}</td></tr>" for i in range(2))
        turn = f"<a aria-label='Next page' href='/runs/{sync}?p={page + 1}'>Next</a>" if page < 5 else ""
        return f"<table><tbody>{rows}</tbody></table>{turn}"

    async def go(limit):
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            async def serve(route):
                path = route.request.url.split("app.data.test", 1)[1]
                sync, _, query = path.removeprefix("/runs/").partition("?p=")
                last = {"a": 3, "b": 1}.get(sync, 99)
                await route.fulfill(body=history(sync, int(query or 1), last), content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            page = await context.new_page()
            agent = BrowserSubAgent(
                "b", None, allow_unsafe_local_execution=confinement_unavailable_reason() is not None,
            )
            agent._context, agent._page = context, page
            agent.site_interval_s = 0
            agent.history_pages = limit
            agent.decision_client = _Judge()
            try:
                return await agent._run_playwright(
                    'runs = await read_pages(\n'
                    '    [f"https://app.data.test/runs/{s}" for s in ("a", "b", "c")],\n'
                    '    "() => [...document.querySelectorAll(\'td\')].map(td => td.innerText)",\n'
                    '    next_page="a[aria-label=\'Next page\']",\n'
                    '    until="() => document.body.innerText.includes(\'Yesterday\')")\n'
                    'result = [(r["pages"], r["more"], r["values"][-1][-1]) for r in runs]'
                )
            finally:
                await agent.teardown()
                await browser.close()

    out = asyncio.run(go(50))
    assert out["status"] == "success", out.get("error")
    # a reaches the period's start on page 3, b on page 1, c runs out of pages after 5
    assert out["result"] == [[3, False, "Yesterday run a.3.1"], [1, False, "Yesterday run b.1.1"],
                             [5, False, "Today run c.5.1"]]
    capped = asyncio.run(go(2))
    assert capped["result"][2] == [2, True, "Today run c.2.1"]


def test_a_filtering_script_reads_a_history_to_its_end():
    labels = {1: "Today", 2: "Today", 3: "Oct 16", 4: "Oct 15"}

    def history(page: int) -> str:
        turn = f"<a aria-label='Next' href='/runs?p={page + 1}'>Next</a>" if page < 4 else ""
        return f"<table><tbody><tr><td>{labels[page]} run {page}</td></tr></tbody></table>{turn}"

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            async def serve(route):
                page = int(route.request.url.partition("?p=")[2] or 1)
                await route.fulfill(body=history(page), content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            agent = BrowserSubAgent("b", None)
            agent._context = context
            agent._page = await context.new_page()
            agent.site_interval_s = 0
            try:
                return await agent._read_pages(
                    ["https://app.data.test/runs"],
                    "() => [...document.querySelectorAll('td')].map(td => td.innerText)"
                    ".filter(t => t.startsWith('Oct 16'))",
                    next_page="a[aria-label='Next']",
                    until="() => document.body.innerText.includes('Oct 15')",
                )
            finally:
                await agent.teardown()
                await browser.close()

    record = asyncio.run(go())[0]
    assert record["stop_reason"] == "until" and record["pages"] == 4
    assert record["values"] == [[], [], ["Oct 16 run 3"], []]


def test_until_judges_the_rows_the_script_returned_on_that_page():
    labels = {1: ["Today"], 2: ["Oct 16", "Oct 16"], 3: ["Oct 16", "Oct 14"], 4: ["Oct 13"]}

    def history(page: int) -> str:
        cells = "".join(f"<tr><td>{label} run</td></tr>" for label in labels[page])
        turn = f"<a aria-label='Next' href='/runs?p={page + 1}'>Next</a>" if page < 4 else ""
        return f"<table><tbody>{cells}</tbody></table>{turn}"

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            async def serve(route):
                page = int(route.request.url.partition("?p=")[2] or 1)
                await route.fulfill(body=history(page), content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            agent = BrowserSubAgent("b", None)
            agent._context = context
            agent._page = await context.new_page()
            agent.site_interval_s = 0
            try:
                return await agent._read_pages(
                    ["https://app.data.test/runs"],
                    "() => [...document.querySelectorAll('td')].map(td => td.innerText)",
                    next_page="a[aria-label='Next']",
                    until="rows => rows.some(row => row.startsWith('Oct 14') || row.startsWith('Oct 13'))",
                )
            finally:
                await agent.teardown()
                await browser.close()

    record = asyncio.run(go())[0]
    assert record["stop_reason"] == "until" and record["pages"] == 3


def test_open_each_refuses_items_the_list_does_not_have_before_opening_any():
    listing = "<table>" + "".join(
        f"<tr class='row' onclick=\"location.href='/syncs/{i}'\"><td>Sync {i}</td></tr>" for i in range(3)
    ) + "</table>"

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            async def serve(route):
                await route.fulfill(body=listing, content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            agent = BrowserSubAgent("b", None)
            agent._context = context
            agent._page = await context.new_page()
            agent.site_interval_s = 0
            try:
                started = time.monotonic()
                with pytest.raises(ValueError, match=r"matches 0 item\(s\).*\[0, 1\] do not exist"):
                    await agent._open_each("https://app.data.test/syncs", "[role='row']", [0, 1], "() => 1")
                return time.monotonic() - started, len(context.pages)
            finally:
                await agent.teardown()
                await browser.close()

    took, pages = asyncio.run(go())
    assert took < 8 and pages == 1


def test_reading_an_element_that_is_not_there_fails_at_once():
    started = time.monotonic()
    out, _ = _run('result = await page.locator("main").inner_text()')
    assert out["status"] == "error" and "matches nothing" in out["error"]
    assert time.monotonic() - started < 20


def test_paged_history_preserves_read_pages_when_a_later_page_fails():
    async def go():
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()

            async def serve(route):
                second = "?page=2" in route.request.url
                await route.fulfill(
                    body=("<main>second</main>" if second else
                          "<main>first</main><a href='?page=2' aria-label='Next'>Next</a>"),
                    content_type="text/html",
                )

            await context.route("https://app.data.test/**", serve)
            agent = BrowserSubAgent("b", None)
            agent._context = context
            agent._page = await context.new_page()
            agent.site_interval_s = 0
            try:
                return await agent._read_pages(
                    ["https://app.data.test/history"],
                    "() => { if (location.search) throw Error('read failed'); "
                    "return document.querySelector('main').innerText; }",
                    next_page="a[aria-label='Next']",
                )
            finally:
                await agent.teardown()
                await browser.close()

    result = asyncio.run(go())[0]
    assert result["values"] == ["first"]
    assert result["pages"] == 1
    assert result["more"] is True
    assert "read failed" in result["error"]


def test_batch_deadline_returns_completed_items_and_closes_worker_tabs():
    async def go():
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            stalled = asyncio.Event()
            page_events = []

            def track_page(page):
                page_events.append(("opened", id(page)))
                page.on("close", lambda: page_events.append(("closed", id(page))))

            context.on("page", track_page)

            async def serve(route):
                if route.request.url.endswith("/slow"):
                    await stalled.wait()
                await route.fulfill(body="<main>completed</main>", content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            agent = BrowserSubAgent("b", None)
            agent._context = context
            agent._page = await context.new_page()
            agent.site_interval_s = 0
            agent._settle = AsyncMock()
            agent._page_broker = SimpleNamespace(deadline=asyncio.get_running_loop().time() + 5)
            try:
                result = await agent._read_pages(
                    ["https://app.data.test/fast", "https://app.data.test/slow", "https://app.data.test/later"],
                    "() => document.querySelector('main').innerText", concurrency=1,
                )
                assert len(context.pages) == 1, {
                    "records": result,
                    "pages": [(id(page), page.url) for page in context.pages],
                    "events": page_events,
                    "tasks": [str(task.get_coro()) for task in asyncio.all_tasks()],
                }
                return result
            finally:
                stalled.set()
                await agent.teardown()
                await browser.close()

    result = asyncio.run(go())
    assert result[0]["value"] == "completed"
    assert [item["url"] for item in result] == [
        "https://app.data.test/fast", "https://app.data.test/slow", "https://app.data.test/later",
    ]
    assert all(item["stop_reason"] == "timeout" for item in result[1:])


def test_only_programs_that_produced_findings_are_kept_as_the_method():
    from jarviscore.execution.isolation import confinement_unavailable_reason

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(RUNS)
            agent = BrowserSubAgent(
                "b", None, allow_unsafe_local_execution=confinement_unavailable_reason() is not None,
            )
            agent._page = page
            agent.decision_client = _Judge()
            try:
                await agent._run_playwright('result = await page.locator("table").aria_snapshot()')
                await agent._run_playwright('state["rows"] = await page.locator("tr").all_inner_texts()')
                await agent._run_playwright('raise ValueError("broken")')
                return agent._programs
            finally:
                await agent.teardown()
                await browser.close()

    programs = asyncio.run(go())
    assert [program["wrote"] for program in programs] == [["rows"]]


def test_code_opens_each_linkless_item_of_a_list_at_once():
    from jarviscore.execution.isolation import confinement_unavailable_reason

    listing = "<table>" + "".join(
        f"<tr class='row' onclick=\"location.href='/syncs/{i}'\"><td>Sync {i}</td></tr>" for i in range(3)
    ) + "</table>"

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            async def serve(route):
                path = route.request.url.split("app.data.test", 1)[1]
                body = listing if path == "/syncs" else f"<main>runs of {path.rsplit('/', 1)[1]}</main>"
                await route.fulfill(body=body, content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            page = await context.new_page()
            agent = BrowserSubAgent(
                "b", None, allow_unsafe_local_execution=confinement_unavailable_reason() is not None,
            )
            agent._context, agent._page = context, page
            agent.site_interval_s = 0
            agent.decision_client = _Judge()
            try:
                out = await agent._run_playwright(
                    'state["syncs"] = await open_each("https://app.data.test/syncs", "tr.row",'
                    ' "() => document.querySelector(\'main\').innerText")\n'
                    'result = [(s["url"], s["value"]) for s in state["syncs"]]'
                )
                return out, len(context.pages)
            finally:
                await agent.teardown()
                await browser.close()

    out, open_pages = asyncio.run(go())
    assert out["status"] == "success", out.get("error")
    assert out["result"] == [[f"https://app.data.test/syncs/{i}", f"runs of {i}"] for i in range(3)]
    assert open_pages == 1


def test_code_opens_the_filtered_items_it_holds_as_a_locator():
    from jarviscore.execution.isolation import confinement_unavailable_reason

    listing = "<table>" + "".join(
        f"<tr class='row' onclick=\"location.href='/syncs/{i}'\"><td>Sync {i}</td>"
        f"<td>{'1 alert' if i % 2 == 0 else 'No alerts'}</td></tr>" for i in range(4)
    ) + "</table>"

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            async def serve(route):
                path = route.request.url.split("app.data.test", 1)[1]
                body = listing if path == "/syncs" else f"<main>runs of {path.rsplit('/', 1)[1]}</main>"
                await route.fulfill(body=body, content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            page = await context.new_page()
            await page.goto("https://app.data.test/syncs")
            agent = BrowserSubAgent(
                "b", None, allow_unsafe_local_execution=confinement_unavailable_reason() is not None,
            )
            agent._context, agent._page = context, page
            agent.site_interval_s = 0
            agent.decision_client = _Judge()
            try:
                return await agent._run_playwright(
                    'rows = page.locator("tr").filter(has_text="1 alert")\n'
                    'opened = await open_each(rows, "() => document.querySelector(\'main\').innerText")\n'
                    'result = [(s["index"], s["url"], s["value"]) for s in opened]'
                )
            finally:
                await agent.teardown()
                await browser.close()

    out = asyncio.run(go())
    assert out["status"] == "success", out.get("error")
    assert out["result"] == [
        [0, "https://app.data.test/syncs/0", "runs of 0"],
        [1, "https://app.data.test/syncs/2", "runs of 2"],
    ]


def test_a_program_moves_the_page_once_and_reads_other_addresses_as_a_collection():
    from jarviscore.execution.isolation import confinement_unavailable_reason

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            agent = BrowserSubAgent(
                "b", None, allow_unsafe_local_execution=confinement_unavailable_reason() is not None,
            )
            agent._page = page
            agent.site_interval_s = 0
            agent.decision_client = _Judge()
            try:
                walked = await agent._run_playwright(
                    'await page.goto("data:text/html,<h1>A</h1>")\n'
                    'state["a"] = await page.locator("h1").inner_text()\n'
                    'await page.goto("data:text/html,<h1>B</h1>")\n'
                    'state["b"] = await page.locator("h1").inner_text()'
                )
                next_program = await agent._run_playwright(
                    'await page.goto("data:text/html,<h1>C</h1>")\n'
                    'result = await page.locator("h1").inner_text()'
                )
                return walked, next_program, agent._browser_findings
            finally:
                await agent.teardown()
                await browser.close()

    walked, next_program, findings = asyncio.run(go())
    assert walked["status"] == "error" and walked["error_type"] == "PermissionError"
    assert "read_pages" in walked["error"] and "open_each" in walked["error"]
    assert findings == {"a": "A"}
    assert [action["action"] for action in walked["actions"]] == ["goto"]
    assert next_program["status"] == "success" and next_program["result"] == "C"


def test_programs_compute_over_the_steps_collection_records_by_what_they_read():
    from jarviscore.execution.isolation import confinement_unavailable_reason

    item = "https://a.test/l#tr#0"

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            agent = BrowserSubAgent(
                "b", None, allow_unsafe_local_execution=confinement_unavailable_reason() is not None,
            )
            agent._page = page
            agent.decision_client = _Judge()
            agent._browser_reads = [
                {"kind": "read_pages", "url": "https://a.test/1", "error": "boom", "stop_reason": "error"},
                {"kind": "open_each", "list": "https://a.test/l", "selector": "tr", "index": 0,
                 "error": "Timeout"},
                {"kind": "read_pages", "url": "https://a.test/1", "values": ["x"], "stop_reason": "end"},
            ]
            try:
                first = await agent._run_playwright(
                    'result = {k: r.get("stop_reason") for k, r in reads.items()}'
                )
                agent._remember_read("open_each", {
                    "list": "https://a.test/l", "selector": "tr", "index": 0,
                    "url": "https://a.test/s/0", "value": "sync 0",
                })
                second = await agent._run_playwright(
                    f'result = [reads["https://a.test/1"]["values"], reads["{item}"]["value"]]'
                )
                return first, second
            finally:
                await agent.teardown()
                await browser.close()

    first, second = asyncio.run(go())
    assert first["status"] == "success", first.get("error")
    assert first["result"] == {"https://a.test/1": "end", item: None}
    assert second["result"] == [["x"], "sync 0"]


def test_an_unfinished_read_never_replaces_a_finished_one():
    agent = BrowserSubAgent("b", None)
    agent._browser_reads = [
        {"kind": "read_pages", "url": "https://a.test/runs", "values": [["run 1"], ["run 2"]],
         "pages": 2, "more": False, "stop_reason": "until"},
        {"kind": "read_pages", "url": "https://a.test/runs", "values": [[]], "pages": 1,
         "more": True, "stop_reason": "unchanged"},
        {"kind": "read_pages", "url": "https://a.test/other", "stop_reason": "timeout", "more": True},
    ]

    records = agent._read_records()

    assert records["https://a.test/runs"]["values"] == [["run 1"], ["run 2"]]
    assert [record["url"] for record in agent._open_read_facts()] == ["https://a.test/other"]


def test_the_calls_behind_the_steps_current_records_are_its_method():
    agent = BrowserSubAgent("b", None)
    literal = {"kind": "read_pages", "urls": ["https://a.test/runs"], "script": "() => rows()",
               "next_page": "a.next", "until": "() => text().includes('Oct 15')"}
    dated = {**literal, "until": "() => oldest() < periodStart"}
    first, second = agent._note_call(literal), agent._note_call(dated)
    assert agent._note_call(dict(literal)) == first
    agent._remember_read("read_pages", {"url": "https://a.test/runs", "values": [[1]] * 50, "pages": 50,
                                        "more": True, "stop_reason": "page_limit"}, first)
    agent._remember_read("read_pages", {"url": "https://a.test/runs", "values": [[1]], "pages": 1,
                                        "more": False, "stop_reason": "until"}, second)

    assert agent._calls_behind_records() == [dated]


def test_reopening_a_failed_list_item_closes_it_and_lists_keep_their_own_items():
    agent = BrowserSubAgent("b", None)
    agent._browser_reads = [
        {"kind": "open_each", "list": "https://a.test/google", "selector": "tr", "index": 0, "error": "Timeout"},
        {"kind": "open_each", "list": "https://a.test/meta", "selector": "tr", "index": 0, "error": "Timeout"},
        {"kind": "open_each", "list": "https://a.test/google", "selector": "tr", "index": 0,
         "url": "https://a.test/s/1", "value": "ok"},
    ]

    assert [record["list"] for record in agent._open_read_facts()] == ["https://a.test/meta"]


def test_a_collection_script_that_is_not_javascript_opens_no_page():
    async def go():
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            agent = BrowserSubAgent("b", None)
            agent._context = context
            agent._page = await context.new_page()
            try:
                with pytest.raises(ValueError, match="not valid JavaScript"):
                    await agent._read_pages(["https://app.data.test/a"], "() => ({rows: [1, 2]]})")
                return len(context.pages)
            finally:
                await agent.teardown()
                await browser.close()

    assert asyncio.run(go()) == 1


def test_a_read_called_as_a_tool_stops_at_the_steps_time_with_what_it_read():
    from jarviscore.kernel.lease import ExecutionLease

    async def go():
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            stalled = asyncio.Event()

            async def serve(route):
                if route.request.url.endswith("/slow"):
                    await stalled.wait()
                await route.fulfill(body="<main>completed</main>", content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            agent = BrowserSubAgent("b", None)
            agent._context = context
            agent._page = await context.new_page()
            agent.site_interval_s = 0
            agent._settle = AsyncMock()
            agent._cognition = SimpleNamespace(lease=ExecutionLease(wall_clock_ms=1500))
            started = time.monotonic()
            try:
                result = await agent._read_pages(
                    ["https://app.data.test/fast", "https://app.data.test/slow"],
                    "() => document.querySelector('main').innerText",
                )
                return result, time.monotonic() - started
            finally:
                stalled.set()
                await agent.teardown()
                await browser.close()

    result, took = asyncio.run(go())
    assert took < 5
    assert result[0]["value"] == "completed"
    assert result[1]["stop_reason"] == "timeout"


def test_open_each_as_a_tool_reopens_only_the_chosen_items():
    listing = "<table>" + "".join(
        f"<tr class='row' onclick=\"location.href='/syncs/{i}'\"><td>Sync {i}</td></tr>" for i in range(3)
    ) + "</table>"

    async def go():
        async with async_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            async def serve(route):
                path = route.request.url.split("app.data.test", 1)[1]
                body = listing if path == "/syncs" else f"<main>runs of {path.rsplit('/', 1)[1]}</main>"
                await route.fulfill(body=body, content_type="text/html")

            await context.route("https://app.data.test/**", serve)
            agent = BrowserSubAgent("b", None)
            agent._context = context
            agent._page = await context.new_page()
            agent.site_interval_s = 0
            agent.decision_client = _Judge()
            try:
                return await agent._tool_open_each(
                    "https://app.data.test/syncs", "tr.row",
                    "() => document.querySelector('main').innerText", indexes=[2],
                )
            finally:
                await agent.teardown()
                await browser.close()

    out = asyncio.run(go())
    assert out["status"] == "success", out
    assert [(r["index"], r["value"], r["list"]) for r in out["results"]] == [
        (2, "runs of 2", "https://app.data.test/syncs"),
    ]


def test_code_learns_at_once_why_an_element_cannot_be_clicked():
    result, _ = _run(
        'import time\n'
        'started = time.monotonic()\n'
        'try:\n'
        '    await page.get_by_role("button", name="Next").click()\n'
        'except Exception as exc:\n'
        '    result = {"error": str(exc), "seconds": time.monotonic() - started}',
        html=RUNS + '<div style="position:fixed;inset:0;background:#fff" aria-label="Cookie consent">'
                    'We use cookies</div>',
    )
    assert "covered by" in result["result"]["error"]
    assert result["result"]["seconds"] < 5


def test_code_clicks_a_boxless_row_instead_of_selecting_its_child_checkbox():
    html = '''<style>table, tbody, tr { display: contents; }
      td { display: inline-flex; width: 160px; height: 36px; }</style>
      <table><tr onclick="document.body.dataset.opened='yes'">
        <td><input type="checkbox" onclick="event.stopPropagation()"></td>
        <td>Open record</td></tr></table>'''
    result, observed = _run(
        'await page.get_by_role("row").click()', html=html,
        after='({opened: document.body.dataset.opened, selected: document.querySelector("input").checked})',
    )
    assert result["status"] == "success", result.get("error")
    assert observed == {"opened": "yes", "selected": False}


def test_an_action_that_commits_the_person_is_refused_and_not_performed():
    judge = _Judge()
    result, paid = _run(
        'try:\n'
        '    await page.locator("#pay").click()\n'
        '    result = "clicked"\n'
        'except ConsequentialActionRefused as exc:\n'
        '    result = str(exc)\n',
        judge=judge, after="document.body.dataset.paid || 'no'",
    )

    assert paid == "no"
    assert "could commit the person" in result["result"] and "irreversible" in result["result"]
    assert result["actions"][0]["refused"] and "Pay £40 now" in judge.asked[0]


def test_enter_in_a_field_is_judged_and_typing_alone_is_not():
    judge = _Judge()
    result, searched = _run(
        'await page.locator("#q").fill("clicks")\n'
        'await page.locator("#q").press("Enter")\n',
        judge=judge, after="document.body.dataset.searched || ''",
    )

    assert result["status"] == "success" and searched == "clicks"
    assert [a["action"] for a in result["actions"]] == ["press"] and len(judge.asked) == 1


def test_the_same_action_is_judged_once_per_run():
    judge = _Judge()
    result, _ = _run(
        'for _ in range(3):\n'
        '    await page.get_by_role("button", name="Next").click()\n',
        judge=judge,
    )

    assert result["status"] == "success" and len(result["actions"]) == 3 and len(judge.asked) == 1


def test_an_action_that_cannot_be_judged_is_not_performed():
    result, _ = _run('await page.get_by_role("button", name="Next").click()\n', judge=_Judge(fail=True))

    assert result["status"] == "error" and "ConsequentialActionRefused" in result["error"]
    assert "could not be judged" in result["error"]


@pytest.mark.parametrize("code", [
    "page.context",
    "page.request",
    "await page.route('**/*', 'x')",
    "await page.screenshot(path='/tmp/x.png')",
    "await page.locator('#q').set_input_files('/etc/hosts')",
    "page._impl_obj",
    "await page.add_script_tag(url='https://example.com/x.js')",
])
def test_code_reaches_only_the_page(code):
    result, _ = _run(code)

    assert result["status"] == "error"
    assert result["error_type"] in {"PermissionError", "AttributeError"}


def test_python_functions_cannot_cross_into_the_page():
    result, _ = _run("await page.wait_for_function(lambda: True)")

    assert result["status"] == "error" and "JavaScript as a string" in result["error"]


def test_waiting_for_a_page_condition_works():
    result, _ = _run(
        'handle = await page.wait_for_function("() => document.querySelectorAll(\'tr\').length > 2")\n'
        'result = await handle.json_value()\n'
    )

    assert result["status"] == "success" and result["result"] is True


def test_a_property_called_as_a_method_fails_as_playwright_would():
    # Live, an agent wrote rows.first() for the `first` property; the error must name the Locator.
    result, _ = _run("page.locator('tr').first()")

    assert result["status"] == "error"
    assert "'Locator' object is not callable" in result["error"]


def test_navigation_from_code_is_paced_and_recorded(monkeypatch):
    paced = []

    async def pace(self, url):
        paced.append(url)

    monkeypatch.setattr(BrowserSubAgent, "_pace", pace)
    result, _ = _run('await page.goto("data:text/html,<h1>Second</h1>")')

    assert result["status"] == "success" and paced == ["data:text/html,<h1>Second</h1>"]
    assert result["actions"] == [{"action": "goto", "url": "data:text/html,<h1>Second</h1>"}]


def test_code_that_runs_too_long_is_stopped_with_what_it_did(monkeypatch):
    monkeypatch.setattr(browser_module, "_CODE_DEADLINE_GRACE_S", 1)
    result, _ = _run(
        'state["inventory"] = ["known"]\n'
        'await page.get_by_role("button", name="Next").click()\nawait asyncio.sleep(30)\n',
        timeout_s=3,
    )

    assert result["status"] == "error" and "did not finish within 3s" in result["error"]
    assert [a["action"] for a in result["actions"]] == ["click"]
    assert result["session_reset"] is True
    assert result["state_keys"] == ["inventory"]


def test_browser_artifact_carries_structured_state_to_followup_steps(monkeypatch):
    from jarviscore.kernel.subagent import BaseSubAgent

    async def run_cell(agent, *args, **kwargs):
        observed = await agent._run_playwright('state["inventory"] = ["stable-url"]')
        assert observed["status"] == "success"
        return SimpleNamespace(status="success", payload={"answer": "checked"}, metadata={})

    monkeypatch.setattr(BaseSubAgent, "run", run_cell)

    async def exercise():
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            agent = BrowserSubAgent("b", None)
            agent._page = await browser.new_page()
            try:
                output = await agent.run("check")
                assert output.payload == {
                    "answer": "checked", "browser_state": {"inventory": ["stable-url"]},
                    "browser_programs": ['state["inventory"] = ["stable-url"]'],
                }
            finally:
                await agent.teardown()
                await browser.close()

    asyncio.run(exercise())


def test_run_playwright_never_takes_an_irreversible_flag():
    agent = BrowserSubAgent("b", None)
    agent.redis_store = None

    result = asyncio.run(agent._execute_tool(
        "run_playwright", {"code": "pass", "irreversible": True, "consequence": "Pays"},
    ))

    assert result["semantic_error"] == "IRREVERSIBLE_NEEDS_EXACT_ELEMENT"


def test_code_is_offered_only_where_it_can_be_confined(monkeypatch):
    from jarviscore.execution import isolation

    monkeypatch.setattr(isolation, "confinement_unavailable_reason", lambda: "no sandbox here")

    assert "run_playwright" not in BrowserSubAgent("b", None)._tools
    assert "run_playwright" in BrowserSubAgent("b", None, allow_unsafe_local_execution=True)._tools


def test_the_browser_offers_the_agreed_tools():
    tools = set(BrowserSubAgent("b", None, allow_unsafe_local_execution=True)._tools)

    assert {
        "navigate", "snapshot", "click", "type_text", "fill_form", "select_option",
        "screenshot", "read_pages", "open_each", "run_playwright",
    } <= tools
    assert not tools & {
        "evaluate", "wait_for", "get_text", "get_links", "scroll", "get_attribute",
        "get_cookies", "close_page", "install_required",
    }
    assert "run_playwright" not in browser_module.BrowserSubAgent.perception_tools


def test_code_findings_are_not_replaced_by_a_later_page_snapshot():
    from jarviscore.kernel.subagent import _thread_history

    messages = []
    _thread_history(messages, [
        {"assistant": "Extract inventory", "observation": "inventory: 23 sync URLs",
         "perception": "run_playwright" in BrowserSubAgent.perception_tools,
         "superseded": "old page"},
        {"assistant": "Look again", "observation": "current page", "perception": True,
         "superseded": "old page"},
    ])
    assert "inventory: 23 sync URLs" in [message["content"] for message in messages]
