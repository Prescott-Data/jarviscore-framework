"""What a browser page sends is decided where it leaves the browser, and recorded."""
import asyncio
import http.server
import json
import threading

import pytest


from jarviscore.control import policy as policy_module
from jarviscore.control.browser_requests import attach
from jarviscore.evidence import journal as journal_module
from jarviscore.evidence.journal import Journal, verify

playwright = pytest.importorskip("playwright.async_api")

PAGE = """<!doctype html><html><body><p id=p>shop</p>
<img src="/pixel.png">
<script>
async function send(host) {
  try { const r = await fetch(`http://${host}/api/order`, {method: "POST", body: "item=42"}); return r.status; }
  catch (e) { return "blocked"; }
}
</script></body></html>"""


class Server:
    def __init__(self):
        self.received = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, body=b"ok", kind="text/plain"):
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.received.append(("GET", self.headers.get("Host"), self.path))
                self._reply(PAGE.encode(), "text/html") if self.path == "/" else self._reply()

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.received.append(("POST", self.headers.get("Host"), self.path, self.rfile.read(length)))
                self._reply()

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST")
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def posts(self, host):
        return [r for r in self.received if r[0] == "POST" and r[1].startswith(host)]


@pytest.fixture
def server():
    running = Server()
    yield running
    running.httpd.shutdown()


@pytest.fixture
def control(monkeypatch, tmp_path):
    def configure(mode="strict", effects=None):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({"effects": effects or []}))
        monkeypatch.setenv("JARVISCORE_CONTROL_MODE", mode)
        monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(path))
        monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
        monkeypatch.setattr(policy_module, "_cached", None)
        monkeypatch.setattr(journal_module, "_journal", None)
        return str(tmp_path / "journal")
    return configure


async def browse(server, sends_to, brokers=None):
    """Open the shop page on 127.0.0.1 and have it POST to each host in ``sends_to``."""
    async with playwright.async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            broker = await attach(context, {"workflow_id": "wf", "step_id": "s1", "agent": "browser-1"})
            if brokers is not None:
                brokers.append(broker)
            page = await context.new_page()
            await page.goto(f"http://127.0.0.1:{server.port}/")
            results = [await page.evaluate(f"send('{host}:{server.port}')") for host in sends_to]
            await asyncio.sleep(0.2)
            return results
        finally:
            await browser.close()


def decisions(root):
    with open(Journal(root).run_path("wf/s1"), encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle]
    return [e["data"] for e in events if e["kind"] == "policy.decision" and e["data"].get("sink") == "browser"]


@pytest.mark.asyncio
async def test_strict_mode_lets_a_page_send_to_its_own_site_and_stops_it_sending_elsewhere(control, server):
    root = control("strict")

    own, elsewhere = await browse(server, ["127.0.0.1", "localhost"])

    assert own == 200 and elsewhere == "blocked"
    assert len(server.posts("127.0.0.1")) == 1 and server.posts("localhost") == []
    by_target = {(d["action"], d["attributes"]["host"]): d for d in decisions(root)}
    assert by_target[("navigate", "127.0.0.1")]["outcome"] == "allow"
    assert by_target[("send", "127.0.0.1")]["outcome"] == "allow"
    refused = by_target[("send", "localhost")]
    assert refused["outcome"] == "deny" and refused["rule"] == "browser-send-off-site"
    assert refused["attributes"]["page"] == "127.0.0.1" and refused["agent"] == "browser-1"
    assert verify(root).ok, verify(root).problems


@pytest.mark.asyncio
async def test_reads_the_page_makes_pass_without_a_decision(control, server):
    root = control("strict")

    await browse(server, [])

    assert ("GET", f"127.0.0.1:{server.port}", "/pixel.png") in server.received
    assert [d["action"] for d in decisions(root)] == ["navigate"]


@pytest.mark.asyncio
async def test_a_deployment_can_allow_a_host_its_pages_send_to(control, server):
    root = control("strict", [
        {"name": "our-api", "decision": "allow", "match": {"sink": "browser", "target": "localhost/api/*"}},
    ])

    assert await browse(server, ["localhost"]) == [200]
    assert len(server.posts("localhost")) == 1
    assert decisions(root)[-1]["rule"] == "deployment:our-api"


@pytest.mark.asyncio
async def test_a_deployment_can_keep_the_browser_off_a_site(control, server):
    control("strict", [{"name": "not-there", "decision": "deny", "match": {"sink": "browser", "target": "127.0.0.1/*"}}])

    with pytest.raises(Exception):
        await browse(server, [])
    assert not [r for r in server.received if r[2] == "/"]


@pytest.mark.asyncio
async def test_report_mode_records_what_strict_would_refuse_and_holds_nothing(control, server):
    root = control("report")

    assert await browse(server, ["localhost"]) == [200]

    refused = [d for d in decisions(root) if d["action"] == "send"][0]
    assert refused["outcome"] == "deny" and refused["enforced"] is False
    assert len(server.posts("localhost")) == 1


def test_every_browser_context_the_package_creates_is_brokered():
    import ast
    import pathlib

    package = pathlib.Path(__file__).resolve().parents[1] / "jarviscore"
    # connect_over_cdp returns a browser; its context is taken where these are called.
    creators = {"new_context", "launch_persistent_context"}
    unbrokered = []
    for path in sorted(package.rglob("*.py")):
        if "data/" in path.relative_to(package).as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {
                n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                for n in ast.walk(node) if isinstance(n, ast.Call)
            }
            if calls & creators and "attach" not in calls:
                unbrokered.append(f"{path.relative_to(package)}:{node.name}")
    assert unbrokered == [], f"Browser contexts created without the request broker: {unbrokered}"


def test_an_off_site_send_is_refused_by_the_built_in_rule_and_liftable():
    from jarviscore.control.effects import Effect, _builtin_refusal

    send = Effect("browser", "send", target="evil.test/x", origin="page",
                  attributes={"host": "evil.test", "page": "shop.test"})
    assert _builtin_refusal(send)[0] == "browser-send-off-site"
    assert _builtin_refusal(Effect("browser", "send", attributes={"host": "shop.test", "page": "shop.test"})) is None
    assert _builtin_refusal(Effect("browser", "navigate", attributes={"host": "evil.test", "page": "shop.test"})) is None



@pytest.mark.asyncio
async def test_the_broker_keeps_what_each_action_really_sent_for_the_agent_to_report(control, server):
    control("strict")
    brokers = []

    await browse(server, ["127.0.0.1", "localhost"], brokers)

    assert [(s["to"], s["outcome"]) for s in brokers[0].sent] == [
        ("127.0.0.1/api/order", "sent"), ("localhost/api/order", "refused"),
    ]


@pytest.mark.asyncio
async def test_a_page_the_person_may_not_read_is_refused_in_a_frame_or_fetch_too(control, server, tmp_path):
    """Review: an iframe or fetch reached a scoped page that only navigations were held to."""
    from jarviscore import OnBehalfOf, act_for

    root = control("report")
    (tmp_path / "policy.json").write_text(json.dumps({"scopes": {"require": [{
        "name": "finance", "match": {"sink": "browser", "target": "localhost/finance/*"},
        "requires": "finance.reports.read"}]}}))
    policy_module._cached = None

    async def read_finance(person):
        before = len(server.received)
        with act_for(person):
            async with playwright.async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    context = await browser.new_context()
                    await attach(context, {"workflow_id": "wf", "step_id": "s1", "agent": "browser-1"})
                    page = await context.new_page()
                    await page.goto(f"http://127.0.0.1:{server.port}/")
                    await page.evaluate(f"""() => {{
                        const f = document.createElement('iframe');
                        f.src = 'http://localhost:{server.port}/finance/q3'; document.body.appendChild(f);
                        fetch('http://localhost:{server.port}/finance/q4').catch(() => null);
                    }}""")
                    await asyncio.sleep(0.5)
                finally:
                    await browser.close()
        return [r for r in server.received[before:] if r[2].startswith("/finance")]

    assert await read_finance(OnBehalfOf.of("acme", "dave", scopes=[])) == []
    allowed = await read_finance(OnBehalfOf.of("acme", "erin", scopes=["finance.reports.read"]))
    assert {r[2] for r in allowed} == {"/finance/q3", "/finance/q4"}
    refused = [d for d in decisions(root) if d["rule"] == "scope-missing"]
    assert {d["target"] for d in refused} == {"localhost/finance/q3", "localhost/finance/q4"}
    assert all(d["enforced"] and d["acting_for"] == "acme/dave" for d in refused)
    assert verify(root).ok, verify(root).problems


@pytest.mark.asyncio
async def test_a_browser_reused_by_another_persons_run_is_decided_for_that_person(control, server, tmp_path):
    from jarviscore import OnBehalfOf, act_for

    root = control("report")
    (tmp_path / "policy.json").write_text(json.dumps({"scopes": {"require": [{
        "name": "finance", "match": {"sink": "browser", "target": "localhost/finance/*"},
        "requires": "finance.reports.read"}]}}))
    policy_module._cached = None
    erin = OnBehalfOf.of("acme", "erin", scopes=["finance.reports.read"])
    dave = OnBehalfOf.of("acme", "dave", scopes=[])

    with act_for(erin):  # the browser and its event handlers start in Erin's work
        async with playwright.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                await attach(context, {"workflow_id": "wf", "step_id": "s1"})
                page = await context.new_page()
                await page.goto(f"http://127.0.0.1:{server.port}/")
                with act_for(dave):  # Dave's run reuses it
                    await attach(context, {"workflow_id": "wf", "step_id": "s1"})
                    before = len(server.received)
                    await page.evaluate(f"fetch('http://localhost:{server.port}/finance/q3').catch(() => null)")
                    await asyncio.sleep(0.4)
                    assert not [r for r in server.received[before:] if r[2].startswith("/finance")]
            finally:
                await browser.close()
    refused = [d for d in decisions(root) if d["rule"] == "scope-missing"]
    assert refused and all(d["acting_for"] == "acme/dave" for d in refused)
