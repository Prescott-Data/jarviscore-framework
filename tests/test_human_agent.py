"""A person is a peer on the mesh: their work is HITL items, answered from wherever they are."""

import asyncio
import io

import pytest

from jarviscore.hitl import HITLQueue
from jarviscore.human import HumanAgent, HumanChannel, TerminalChannel
from jarviscore.human.channels import from_hitl_decision, readable, to_hitl_decision
from jarviscore.profiles import CustomAgent


class AnsweringChannel(HumanChannel):
    """A person who answers every item with the next scripted answer."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.shown = []

    async def show(self, item):
        self.shown.append(item)
        if self.answers:
            decision, response, by = self.answers.pop(0)
            self.agent.answer(item["id"], decision, response, by=by)


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


async def person(name="alice", capabilities=("review",), channel=None, **options):
    agent = HumanAgent(name, list(capabilities), channel=channel, **options)
    agent.poll_interval = 0.02
    await agent.setup()
    return agent


class TestDecisions:

    @pytest.mark.parametrize("decision", ["answered", "approved", "rejected", "declined"])
    def test_each_decision_is_stored_as_a_hitl_decision_and_read_back(self, decision):
        assert from_hitl_decision(to_hitl_decision(decision)) == decision

    def test_unknown_decisions_are_refused(self):
        with pytest.raises(ValueError):
            to_hitl_decision("maybe")

    def test_a_peer_result_is_shown_as_its_answer(self):
        assert readable({"status": "success", "output": {"response": "ship it"}}) == "ship it"


class TestHumanAgent:

    def test_a_person_is_announced_as_a_person(self):
        alice = HumanAgent("alice", ["review"], channel=None)
        assert alice.role == "alice"
        assert alice.capabilities == ["review", "human"]
        assert "person" in alice.description

    def test_a_subclass_declares_who_it_is(self):
        class Legal(HumanAgent):
            role = "legal"
            capabilities = ["contract-review"]

        assert Legal(channel=None).capabilities == ["contract-review", "human"]

    async def test_the_work_is_a_hitl_item_and_the_answer_is_the_result(self, here):
        channel = AnsweringChannel(("approved", "ship it", "alice"))
        alice = await person(channel=channel)
        result = await alice.execute_task({"task": "Is the draft ready?", "context": {
            "workflow_id": "wf-1", "step_id": "review", "capability": "review",
            "previous_step_results": {"draft": {"output": "The draft"}},
        }})

        assert result["status"] == "success"
        assert result["output"] == {"response": "ship it", "decision": "approved", "answered_by": "alice"}
        [item] = channel.shown
        assert item["kind"] == "input_request" and item["targets"] == ["alice"]
        assert item["context"]["workflow_id"] == "wf-1" and item["context"]["capability"] == "review"
        assert "The draft" in item["content"], "the person sees what came before"
        assert alice.waiting() == []

    @pytest.mark.parametrize("decision", ["rejected", "declined"])
    async def test_a_refusal_fails_the_step_with_the_reason(self, here, decision):
        alice = await person(channel=AnsweringChannel((decision, "numbers are wrong", "alice")))
        result = await alice.execute_task({"task": "Sign off the budget", "context": {}})
        assert result["status"] == "failure"
        assert result["error"] == f"alice {decision}: numbers are wrong"

    async def test_silence_times_out_and_the_item_is_withdrawn(self, here):
        class Watching(HumanChannel):
            withdrawn = []

            async def withdraw(self, item_id):
                self.withdrawn.append(item_id)

        channel = Watching()
        alice = await person(channel=channel, answer_timeout=0.1)
        result = await alice.execute_task({"task": "Anyone?", "context": {}})
        assert result["status"] == "failure" and "did not answer" in result["error"]
        assert len(channel.withdrawn) == 1
        assert alice.waiting() == [], "an expired item leaves the inbox"

    async def test_work_waits_in_the_hitl_inbox_and_anyone_can_answer_it(self, here):
        alice = await person(channel=None)
        asked = asyncio.create_task(alice.execute_task({"task": "Approve the copy", "context": {}}))
        queue = HITLQueue(agent_id="dashboard")
        while not queue.inbox("alice"):
            await asyncio.sleep(0.02)
        [item] = queue.inbox("alice")
        queue.resolve(item["id"], to_hitl_decision("answered"), "Change the headline", by="alice")
        result = await asyncio.wait_for(asked, 5)
        assert result["output"]["response"] == "Change the headline"
        assert result["output"]["decision"] == "answered"

    async def test_upstream_uncertainty_is_for_the_person_to_judge(self):
        alice = HumanAgent("alice", ["review"], channel=None)
        verdict = await alice.authorize_dependencies(
            "review", {"draft": "..."}, {"draft": {"verdict": "uncertain"}})
        assert verdict.decision == "allow"


class Writer(CustomAgent):
    role = "writer"
    capabilities = ["writing"]

    async def on_peer_request(self, msg):
        return {"status": "success", "output": "draft"}


class TestReachedAsAPeer:

    @pytest.fixture
    async def mesh(self, monkeypatch, tmp_path):
        from jarviscore import Mesh

        monkeypatch.delenv("P2P_ENABLED", raising=False)
        mesh = Mesh(config={"p2p_enabled": False, "redis_url": None, "hitl_inbox_dir": str(tmp_path)})
        channel = AnsweringChannel(*[("approved", "ship it", "alice")] * 3)
        alice = mesh.add(HumanAgent("alice", ["review"], channel=channel))
        alice.poll_interval = 0.02
        writer = mesh.add(Writer)
        await mesh.start()
        yield mesh, alice, writer, channel
        await mesh.stop()

    async def test_an_agent_asks_a_person_by_capability(self, mesh):
        _, _, writer, channel = mesh
        result = await writer.peers.request_capability("review", "Is the draft ready?")
        assert result["status"] == "success"
        assert result["peer_role"] == "alice"
        assert result["result"]["output"]["response"] == "ship it"
        context = channel.shown[0]["context"]
        assert (context["asked_by"], context["capability"]) == ("writer", "review")

    async def test_anyone_can_ask_for_a_person(self, mesh):
        _, _, writer, _ = mesh
        result = await writer.peers.request_capability("human", "Anyone around?")
        assert result["status"] == "success"

    async def test_a_capability_the_person_lacks_is_refused(self, mesh):
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        _, alice, _, channel = mesh
        reply = await alice._handle_peer_request(IncomingMessage(
            sender="writer", sender_node="local", type=MessageType.REQUEST,
            data={"query": "Deploy it", "capability": "deploy"}, correlation_id="c1",
            timestamp=0,
        ))
        assert reply["status"] == "failure"
        assert channel.shown == []


class TestTerminal:

    @pytest.fixture
    async def console(self, here):
        import queue as stdqueue

        typed = stdqueue.Queue()

        class Keyboard:
            def __iter__(self):
                return self

            def __next__(self):
                line = typed.get()
                if line is None:
                    raise StopIteration
                return line + "\n"

        out = io.StringIO()
        channel = TerminalChannel(input_stream=Keyboard(), output=out)
        alice = await person(channel=channel)
        yield alice, typed, out
        typed.put(None)
        await alice.teardown()

    async def test_the_person_types_an_answer_and_picks_how_to_send_it(self, console):
        alice, typed, out = console
        asked = asyncio.create_task(alice.execute_task({"task": "Review the launch email", "context": {}}))
        while "Review the launch email" not in out.getvalue():
            await asyncio.sleep(0.02)
        typed.put("Too long; cut the second paragraph")
        typed.put("3")
        result = await asyncio.wait_for(asked, 5)
        assert result["status"] == "failure"
        assert result["error"] == "alice rejected: Too long; cut the second paragraph"
        assert "Send it as: 1 answer · 2 approval · 3 rejection · 4 decline" in out.getvalue()

    async def test_items_are_shown_one_at_a_time_in_order(self, console):
        alice, typed, out = console
        first = asyncio.create_task(alice.execute_task({"task": "First question", "context": {}}))
        while "First question" not in out.getvalue():
            await asyncio.sleep(0.02)
        second = asyncio.create_task(alice.execute_task({"task": "Second question", "context": {}}))
        await asyncio.sleep(0.2)
        assert "Second question" not in out.getvalue()
        typed.put("one")
        typed.put("")
        assert (await asyncio.wait_for(first, 5))["output"]["response"] == "one"
        while "Second question" not in out.getvalue():
            await asyncio.sleep(0.02)
        typed.put("two")
        typed.put("2")
        assert (await asyncio.wait_for(second, 5))["output"]["decision"] == "approved"


class TestCli:

    async def test_inbox_and_answer(self, here, capsys):
        from jarviscore.cli.human import main

        alice = await person(channel=None)
        asked = asyncio.create_task(alice.execute_task(
            {"task": "Approve the copy", "context": {"capability": "review"}}))
        while not alice.waiting():
            await asyncio.sleep(0.02)
        [item] = alice.waiting()

        main(["inbox", "alice"])
        out = capsys.readouterr().out
        assert item["id"] in out and "Approve the copy" in out and "for alice" in out

        main(["answer", item["id"], "--reject", "Wrong price"])
        assert f"{item['id']}: rejected" in capsys.readouterr().out
        result = await asyncio.wait_for(asked, 5)
        assert result["error"] == "alice rejected: Wrong price"

        with pytest.raises(SystemExit):
            main(["answer", item["id"], "again"])
        assert "is waiting" in capsys.readouterr().out

    def test_an_empty_answer_is_refused(self, here):
        from jarviscore.cli.human import main

        with pytest.raises(SystemExit):
            main(["answer", "hitl-x"])


# ── Across nodes, over real SWIM and ZMQ ─────────────────────────────────────

HUMAN_PORT = 7801


async def _wait_for(condition, timeout: float = 60.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.2)
    return True


@pytest.mark.integration
@pytest.mark.slow
async def test_a_person_and_an_agent_on_different_nodes_work_together(tmp_path, monkeypatch):
    from jarviscore import Mesh

    monkeypatch.delenv("REDIS_URL", raising=False)
    human_node = Mesh(config={
        "p2p_enabled": True, "bind_host": "127.0.0.1", "bind_port": HUMAN_PORT,
        "node_name": "human-alice", "redis_url": None, "hitl_inbox_dir": str(tmp_path),
    })
    alice = human_node.add(HumanAgent("alice", ["review"], channel=None))
    alice.poll_interval = 0.05
    agent_node = Mesh(config={
        "p2p_enabled": True, "bind_host": "127.0.0.1", "bind_port": HUMAN_PORT + 1,
        "node_name": "writer-node", "seed_nodes": f"127.0.0.1:{HUMAN_PORT}", "redis_url": None,
    })
    writer = agent_node.add(Writer)
    await human_node.start()
    await agent_node.start()
    # What mesh.run_forever() starts: the CustomAgent's listener loop.
    listener = asyncio.create_task(writer.run())
    try:
        assert "peer_swim" in human_node.capabilities and "peer_swim" in agent_node.capabilities
        assert await _wait_for(lambda: writer.peers.discover(capability="review")
                               and alice.peers.discover(capability="writing")), "never converged"
        remote = {p["role"]: p for p in writer.peers.list_peers()}["alice"]
        assert remote["location"] == "remote" and "human" in remote["capabilities"]

        # An agent asks the person; the person answers from the HITL inbox.
        asked = asyncio.create_task(writer.peers.request_capability("review", "Ship the post?"))
        assert await _wait_for(alice.waiting, 30)
        [item] = alice.waiting()
        assert item["content"] == "Ship the post?"
        assert (item["context"]["capability"], item["context"]["asked_by"]) == ("review", "writer")
        HITLQueue(agent_id="cli", inbox_dir=str(tmp_path)).resolve(
            item["id"], to_hitl_decision("approved"), "ship it", by="alice")

        result = await asyncio.wait_for(asked, 30)
        assert result["status"] == "success", result
        assert result["peer_role"] == "alice"
        assert result["result"]["output"] == {
            "response": "ship it", "decision": "approved", "answered_by": "alice"}

        # The person asks the agent back.
        reply = await alice.peers.request_capability("writing", "Draft a tagline", timeout=30)
        assert reply["status"] == "success", reply
        assert readable(reply["result"]) == "draft"
    finally:
        writer.request_shutdown()
        listener.cancel()
        await agent_node.stop()
        await human_node.stop()
