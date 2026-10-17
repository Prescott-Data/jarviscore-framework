"""A person is a peer on the mesh: reached by capability, answering through a channel."""

import asyncio
import io
import json
import os

import pytest

from jarviscore.human import (
    HumanAnswer,
    HumanChannel,
    InboxChannel,
    TerminalChannel,
    WorkItem,
    answer_item,
    open_items,
)
from jarviscore.human.channels import readable
from jarviscore.profiles import CustomAgent, HumanAgent


class ScriptedChannel(HumanChannel):
    """Answers every task with the next scripted answer, recording what it saw."""

    def __init__(self, *answers: HumanAnswer):
        self.answers = list(answers)
        self.seen = []

    async def ask(self, item):
        self.seen.append(item)
        return self.answers.pop(0)


class SilentChannel(HumanChannel):
    async def ask(self, item):
        await asyncio.Event().wait()


# ── Answers ──────────────────────────────────────────────────────────────────

class TestAnswers:

    @pytest.mark.parametrize("line,decision,response", [
        ("Looks good", "answered", "Looks good"),
        ("/approve", "approved", ""),
        ("/approve ship it", "approved", "ship it"),
        ("/reject numbers are wrong", "rejected", "numbers are wrong"),
        ("/decline not my area", "declined", "not my area"),
        ("/approved is not a command", "answered", "/approved is not a command"),
    ])
    def test_a_line_becomes_an_answer(self, line, decision, response):
        answer = HumanAnswer.parse(line, by="alice")
        assert (answer.decision, answer.response, answer.by) == (decision, response, "alice")

    def test_unknown_decisions_are_refused(self):
        with pytest.raises(ValueError):
            HumanAnswer("maybe")

    def test_a_peer_result_is_shown_as_its_answer(self):
        envelope = {"status": "success", "output": {"response": "42", "decision": "answered"}}
        assert readable(envelope) == "42"
        assert readable({"status": "success", "output": "plain"}) == "plain"


# ── The agent ────────────────────────────────────────────────────────────────

class TestHumanAgent:

    def test_a_person_is_announced_as_a_person(self):
        alice = HumanAgent("alice", ["review"], channel=ScriptedChannel())
        assert alice.role == "alice"
        assert alice.capabilities == ["review", "human"]
        assert "person" in alice.description
        assert "alice" in alice.capability_descriptions["review"]

    def test_a_subclass_declares_who_it_is(self):
        class Legal(HumanAgent):
            role = "legal"
            capabilities = ["contract_review"]

        legal = Legal(agent_id="legal-1", channel=ScriptedChannel())
        assert (legal.role, legal.agent_id) == ("legal", "legal-1")
        assert legal.capabilities == ["contract_review", "human"]
        assert Legal.capabilities == ["contract_review"]

    async def test_the_answer_is_the_result(self):
        channel = ScriptedChannel(HumanAnswer("answered", "Ship Tuesday", "alice"))
        alice = HumanAgent("alice", ["review"], channel=channel)

        result = await alice.execute_task({
            "task": "When do we ship?",
            "context": {
                "capability": "review", "workflow_id": "wf-1", "step_id": "review",
                "previous_step_results": {"draft": {"text": "x" * 5000}},
            },
        })

        assert result["status"] == "success"
        assert result["output"] == {"response": "Ship Tuesday", "decision": "answered",
                                    "answered_by": "alice"}
        assert result["result_summary"]
        item = channel.seen[0]
        assert (item.task, item.capability, item.workflow_id, item.asked_by) == (
            "When do we ship?", "review", "wf-1", "workflow")
        assert len(item.upstream["draft"]) < 1600

    @pytest.mark.parametrize("decision", ["rejected", "declined"])
    async def test_a_refusal_fails_the_task_with_the_reason(self, decision):
        alice = HumanAgent("alice", ["review"],
                           channel=ScriptedChannel(HumanAnswer(decision, "numbers are wrong")))
        result = await alice.execute_task({"task": "Approve?"})
        assert result["status"] == "failure"
        assert "numbers are wrong" in result["error"]
        assert result["output"]["decision"] == decision

    async def test_silence_times_out(self):
        alice = HumanAgent("alice", ["review"], channel=SilentChannel(), answer_timeout=0.05)
        result = await alice.execute_task({"task": "Anyone?"})
        assert result["status"] == "failure"
        assert "did not answer" in result["error"]

    async def test_upstream_uncertainty_is_for_the_person_to_judge(self):
        alice = HumanAgent("alice", ["review"], channel=ScriptedChannel())
        verdict = await alice.authorize_dependencies(
            "review", {"draft": "..."}, {"draft": {"verdict": "uncertain"}})
        assert verdict.decision == "allow"


# ── Reached as a peer ────────────────────────────────────────────────────────

class Writer(CustomAgent):
    role = "writer"
    capabilities = ["writing"]

    async def on_peer_request(self, msg):
        return {"status": "success", "output": "draft"}


class TestReachedAsAPeer:

    @pytest.fixture
    async def mesh(self, monkeypatch):
        from jarviscore import Mesh

        monkeypatch.delenv("P2P_ENABLED", raising=False)
        mesh = Mesh(config={"p2p_enabled": False, "redis_url": None})
        channel = ScriptedChannel(HumanAnswer("approved", "ship it", "alice"))
        alice = mesh.add(HumanAgent("alice", ["review"], channel=channel))
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
        assert channel.seen[0].asked_by == "writer"
        assert channel.seen[0].capability == "review"

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
        assert channel.seen == []


# ── Terminal ─────────────────────────────────────────────────────────────────

class FakePeers:
    def __init__(self):
        self.asked = []

    def list_peers(self):
        return [
            {"role": "researcher", "capabilities": ["research"], "location": "remote"},
            {"role": "bob", "capabilities": ["review", "human"], "location": "remote"},
        ]

    async def request_capability(self, capability, question, timeout=None):
        self.asked.append((capability, question))
        return {"status": "success", "peer_role": "researcher",
                "result": {"status": "success", "output": "Found 3 sources"}}


class Console:
    """A terminal channel driven through a real pipe, as stdin would drive it."""

    def __init__(self):
        read_fd, write_fd = os.pipe()
        self.stdin = os.fdopen(read_fd, "r")
        self._writer = os.fdopen(write_fd, "w")
        self.out = io.StringIO()
        self.channel = TerminalChannel(input_stream=self.stdin, output=self.out)
        self.agent = HumanAgent("alice", ["review"], channel=self.channel)
        self.agent.peers = FakePeers()

    async def start(self):
        await self.channel.start(self.agent)

    def type(self, line):
        self._writer.write(line + "\n")
        self._writer.flush()

    async def wait_for(self, text, timeout=5.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while text not in self.out.getvalue():
            assert asyncio.get_running_loop().time() < deadline, self.out.getvalue()
            await asyncio.sleep(0.01)

    async def close(self):
        self._writer.close()
        await self.channel.stop()


class TestTerminal:

    @pytest.fixture
    async def console(self):
        console = Console()
        await console.start()
        yield console
        await console.close()

    async def test_a_typed_line_answers_the_task_shown(self, console):
        pending = asyncio.create_task(console.channel.ask(
            WorkItem(id="t1", task="Review the launch post", asked_by="writer",
                     capability="review", upstream={"draft": "Hello world"})))
        await console.wait_for("Review the launch post")
        assert "draft: Hello world" in console.out.getvalue()

        console.type("/approve ship it")
        answer = await asyncio.wait_for(pending, 5)

        assert (answer.decision, answer.response, answer.by) == ("approved", "ship it", "alice")

    async def test_tasks_queue_and_are_answered_in_order(self, console):
        first = asyncio.create_task(console.channel.ask(WorkItem(id="t1", task="First?")))
        await console.wait_for("First?")
        second = asyncio.create_task(console.channel.ask(WorkItem(id="t2", task="Second?")))
        await console.wait_for("queued: t2")

        console.type("one")
        await console.wait_for("Second?")
        console.type("two")

        assert (await asyncio.wait_for(first, 5)).response == "one"
        assert (await asyncio.wait_for(second, 5)).response == "two"

    async def test_a_withdrawn_task_makes_way_for_the_next(self, console):
        first = asyncio.create_task(console.channel.ask(WorkItem(id="t1", task="First?")))
        await console.wait_for("First?")
        second = asyncio.create_task(console.channel.ask(WorkItem(id="t2", task="Second?")))
        await console.wait_for("queued: t2")

        first.cancel()
        await console.wait_for("Second?")
        console.type("still here")

        assert (await asyncio.wait_for(second, 5)).response == "still here"

    async def test_a_person_asks_the_mesh_too(self, console):
        console.type("/ask research What changed this week?")
        await console.wait_for("← researcher: Found 3 sources")
        assert console.agent.peers.asked == [("research", "What changed this week?")]

    async def test_peers_are_listed_as_agents_and_people(self, console):
        console.type("/peers")
        await console.wait_for("bob  [person")
        assert "researcher  [agent" in console.out.getvalue()

    async def test_a_line_with_nothing_waiting_is_not_lost_silently(self, console):
        console.type("hello?")
        await console.wait_for("Nothing is waiting on you")


# ── Inbox ────────────────────────────────────────────────────────────────────

class TestInbox:

    @pytest.fixture
    async def inbox(self, tmp_path):
        channel = InboxChannel(str(tmp_path), poll_interval=0.01)
        await channel.start(HumanAgent("alice", ["review"], channel=channel))
        return channel, tmp_path

    async def test_a_task_waits_in_a_file_until_answered(self, inbox):
        channel, root = inbox
        pending = asyncio.create_task(channel.ask(WorkItem(id="t1", task="Approve?")))
        await asyncio.sleep(0.05)

        [item] = open_items(str(root))
        assert (item["id"], item["for"], item["task"]) == ("t1", "alice", "Approve?")
        answer_item("t1", "approved", "fine", directory=str(root))

        answer = await asyncio.wait_for(pending, 5)
        assert (answer.decision, answer.response, answer.by) == ("approved", "fine", "alice")
        assert open_items(str(root)) == []

    async def test_a_withdrawn_task_cannot_be_answered(self, inbox):
        channel, root = inbox
        pending = asyncio.create_task(channel.ask(WorkItem(id="t1", task="Approve?")))
        await asyncio.sleep(0.05)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

        with pytest.raises(LookupError, match="withdrawn"):
            answer_item("t1", "approved", directory=str(root))

    def test_an_unknown_task_is_reported(self, tmp_path):
        with pytest.raises(LookupError, match="No task"):
            answer_item("nope", "answered", "x", directory=str(tmp_path))

    async def test_notices_are_kept(self, inbox):
        channel, root = inbox
        await channel.notify("writer", {"note": "draft v2 is up"})
        line = (root / "alice" / "notices.jsonl").read_text().strip()
        assert json.loads(line)["from"] == "writer"


class TestCli:

    def test_inbox_and_answer(self, tmp_path, capsys):
        from jarviscore.cli.human import main

        task_dir = tmp_path / "alice"
        task_dir.mkdir()
        (task_dir / "t1.json").write_text(json.dumps({
            "id": "t1", "for": "alice", "task": "Approve the post?", "status": "open",
            "capability": "review", "asked_by": "writer", "asked_at": 1}))

        main(["inbox", "--dir", str(tmp_path)])
        assert "t1  for alice  (review · writer)" in capsys.readouterr().out

        main(["answer", "t1", "--reject", "too long", "--dir", str(tmp_path)])
        record = json.loads((task_dir / "t1.json").read_text())
        assert (record["status"], record["decision"], record["response"]) == (
            "answered", "rejected", "too long")

    def test_an_empty_answer_is_refused(self, tmp_path):
        from jarviscore.cli.human import main

        with pytest.raises(SystemExit):
            main(["answer", "t1", "--dir", str(tmp_path)])


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
        "node_name": "human-alice", "redis_url": None,
    })
    alice = human_node.add(HumanAgent(
        "alice", ["review"], channel=InboxChannel(str(tmp_path), poll_interval=0.05)))
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

        # An agent asks the person; the person answers from another process's inbox.
        asked = asyncio.create_task(writer.peers.request_capability("review", "Ship the post?"))
        assert await _wait_for(lambda: open_items(str(tmp_path)), 30)
        [item] = open_items(str(tmp_path))
        assert (item["task"], item["capability"], item["asked_by"]) == (
            "Ship the post?", "review", "writer")
        answer_item(item["id"], "approved", "ship it", directory=str(tmp_path))

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
