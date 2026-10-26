"""Agents do work in a room through the real mesh, and it comes back as a proposal."""

import asyncio
from pathlib import Path

import fakeredis
import pytest

from jarviscore import Mesh
from jarviscore.auth.principal import acting_for
from jarviscore.orchestration.envelopes import DependencyAuthorization
from jarviscore.profiles import CustomAgent
from jarviscore.hitl import HITLQueue
from jarviscore.human import HumanAgent
from jarviscore.room import Person, Room, RoomFeed
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore


alice, bob = Person("acme", "alice", "Alice"), Person("acme", "bob", "Bob")


class FileSandbox:
    """The least an agent needs for the mesh to give it a workspace."""

    def __init__(self, workspace: Path = None):
        self.workspace = workspace

    def for_workspace(self, workspace_dir, **_options):
        return FileSandbox(workspace_dir)


class Coder(CustomAgent):
    role = "coder"
    capabilities = ["coding"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.sandbox = FileSandbox()
        self.tasks = []
        self.acting_for = []

    async def authorize_dependencies(self, task, artifacts, interpretations):
        return DependencyAuthorization("allow", "test")

    async def execute_task(self, task):
        self.tasks.append(task)
        self.acting_for.append(acting_for.get())
        root = Path(task["context"]["workspace_binding"]["path"])
        app = root / "src" / "app.py"
        app.write_text(app.read_text().replace("v1", "v2"))
        (root / "test_app.py").write_text("def test_app(): assert True\n")
        return {"status": "success", "output": "Fixed app.py and added a test"}


class Writer(CustomAgent):
    role = "writer"
    capabilities = ["docs"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.sandbox = FileSandbox()

    async def authorize_dependencies(self, task, artifacts, interpretations):
        return DependencyAuthorization("allow", "test")

    async def execute_task(self, task):
        root = Path(task["context"]["workspace_binding"]["path"])
        assert "v2" in (root / "src" / "app.py").read_text(), "builds on the coder's work"
        (root / "README.md").write_text("# Repo\n\nNow at v2.\n")
        return {"status": "success", "output": "Documented v2"}


class Publisher(CustomAgent):
    role = "publisher"
    capabilities = ["publishing"]
    PDF = b"%PDF-1.4\n\x00\xfe one page\n%%EOF\n"

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.sandbox = FileSandbox()

    async def authorize_dependencies(self, task, artifacts, interpretations):
        return DependencyAuthorization("allow", "test")

    async def execute_task(self, task):
        root = Path(task["context"]["workspace_binding"]["path"])
        (root / "output").mkdir(exist_ok=True)
        (root / "output" / "review.pdf").write_bytes(self.PDF)
        return {"status": "success", "output": "Made the PDF"}


def plan(goal, *steps):
    return {
        "obligations": [{"id": "o1", "description": goal, "source_quote": goal}],
        "steps": [{
            "id": step_id, "capability": capability, "effect": "propose", "systems": [],
            "task": f"{capability} work", "success_criterion": "done",
            "expected_findings": ["done"], "depends_on": depends_on,
            "covers": ["o1"] if index == len(steps) - 1 else [],
        } for index, (step_id, capability, depends_on) in enumerate(steps)],
    }


@pytest.fixture
async def team(tmp_path, monkeypatch):
    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02})
    coder = mesh.add(Coder)
    mesh.add(Writer)
    mesh.add(Publisher)
    await mesh.start()
    room = Room.for_mesh(mesh, "repo", tenant="acme")
    await room.ensure({"src/app.py": "VERSION = 'v1'\n", "README.md": "# Repo\n"}, by=alice)
    room.set_role(bob, "editor", by=alice)
    yield room, coder
    await mesh.stop()


async def text(room, path):
    return (await room.read(path)).decode()


async def test_agents_work_on_the_room_and_propose_their_changes(team):
    room, coder = team

    goal = "Bump the app to v2 and document it"
    asked = await room.ask(goal, asked_by=alice, timeout=20, plan_template=plan(
        goal, ("fix", "coding", []), ("docs", "docs", ["fix"])))

    assert asked.status == "completed", asked.result
    proposal = asked.proposal
    assert proposal.asked_by == "alice" and proposal.base_version == 1
    assert coder.acting_for == ["acme/alice"], "the step ran as the person who asked"
    assert coder.tasks[0]["context"]["room_id"] == "acme/repo", "so memory_scope_field='room_id' scopes it"
    assert proposal.author == "coder, writer"
    assert proposal.paths == ["README.md", "src/app.py", "test_app.py"]
    assert await text(room, "src/app.py") == "VERSION = 'v1'\n", "nothing lands until accepted"

    await room.accept(proposal.id, by=bob)
    assert await text(room, "src/app.py") == "VERSION = 'v2'\n"
    assert await text(room, "README.md") == "# Repo\n\nNow at v2.\n"

    kinds = [event["type"] for event in room.events()]
    assert kinds == ["room.created", "member.changed", "ask.started", "proposal.opened", "ask.finished",
                     "proposal.accepted"], "the room records decisions, not the workflow's steps"
    finished = next(e for e in room.events() if e["type"] == "ask.finished")
    assert finished["proposal"] == proposal.id

    # Each claim in the workflow's ledger names the role that took the step.
    claims = {e["step_id"]: e["role"] for e in room.progress(asked.workflow_id)
              if e["event"] == "step_claimed"}
    assert claims == {"fix": "coder", "docs": "writer"}

    # Progress is read from the workflow's own ledger, with who did each step.
    lines = [item.text for item in RoomFeed(room).poll()]
    assert "plan: fix (coding) → docs (docs)" in lines
    assert "coder took fix" in lines and "coder finished fix" in lines
    assert "writer took docs" in lines and "writer finished docs" in lines
    assert lines.index("writer finished docs") < lines.index(
        f"▲ {proposal.id} proposed by coder, writer for Alice: {goal} (3 files, on v1)")


async def test_a_file_the_agents_write_under_output_is_in_the_proposal(team):
    import hashlib

    room, _ = team
    asked = await room.ask("Make a PDF for compliance", asked_by=alice, timeout=20,
                           title="Compliance PDF", plan_template=plan(
                               "Make a PDF for compliance", ("pdf", "publishing", [])))

    assert asked.proposal.paths == ["output/review.pdf"]
    assert asked.proposal.title == "Compliance PDF"
    assert asked.proposal.changes["output/review.pdf"]["sha256"] == hashlib.sha256(Publisher.PDF).hexdigest()
    await room.accept(asked.proposal.id, by=bob)
    assert await room.read("output/review.pdf") == Publisher.PDF


async def test_a_revision_starts_from_what_the_earlier_attempt_wrote(team):
    room, coder = team
    first = await room.ask("Fix the app", asked_by=alice, timeout=20,
                           plan_template=plan("Fix the app", ("fix", "coding", [])))

    await room.ask("Fix the app, and say why", asked_by=bob, revision_of=first.proposal.id,
                   timeout=20, plan_template=plan("Fix the app", ("fix", "coding", [])))

    objective = coder.tasks[-1]["context"]["objective"]
    assert "The earlier attempt wrote src/app.py, test_app.py. Keep the work in the same files" in objective
    assert "--- src/app.py, as the earlier attempt wrote it ---\nVERSION = 'v2'" in objective
    assert "put new work in a new file" in coder.tasks[-1]["context"]["work_method"]


async def test_work_on_a_proposal_another_revision_replaced_files_nothing(team):
    room, _ = team
    first = await room.ask("Fix the app", asked_by=alice, timeout=20,
                           plan_template=plan("Fix the app", ("fix", "coding", [])))
    taken = await room.propose({"src/app.py": "VERSION = 'v3'\n"}, by=bob, revision_of=first.proposal.id)
    await room.accept(taken.id, by=bob)

    late = await room.ask("Fix the app", asked_by=alice, revision_of=first.proposal.id, timeout=20,
                          plan_template=plan("Fix the app", ("fix", "coding", [])))

    assert late.status == "superseded" and late.proposal is None
    assert f"already replaced by {taken.id}" in late.summary
    assert [p.id for p in room.proposals("open")] == []


async def test_a_rejection_is_passed_to_the_next_attempt(team):
    room, coder = team
    first = await room.ask("Fix the app", asked_by=alice, timeout=20,
                           plan_template=plan("Fix the app", ("fix", "coding", [])))
    await room.reject(first.proposal.id, by=bob, reason="Keep the old test name")

    second = await room.ask("Fix the app", asked_by=alice, revision_of=first.proposal.id,
                            timeout=20, plan_template=plan("Fix the app", ("fix", "coding", [])))

    retry = coder.tasks[-1]["context"]
    assert retry["room"]["feedback"] == {"proposal": first.proposal.id, "decision": "rejected",
                                         "by": "Bob", "reason": "Keep the old test name"}
    assert "rejected by Bob: Keep the old test name" in retry["objective"]
    assert "feedback" not in coder.tasks[0]["context"]["room"]
    assert second.proposal.revision_of == first.proposal.id


async def test_a_conflict_is_explained_to_the_next_attempt(team):
    room, coder = team
    first = await room.ask("Fix the app", asked_by=alice, timeout=20,
                           plan_template=plan("Fix the app", ("fix", "coding", [])))
    mine = await room.propose({"src/app.py": "VERSION = 'v9'\n"}, by=bob)
    await room.accept(mine.id, by=bob)
    with pytest.raises(Exception):
        await room.accept(first.proposal.id, by=alice)

    await room.ask("Fix the app", asked_by=alice, revision_of=first.proposal.id,
                   timeout=20, plan_template=plan("Fix the app", ("fix", "coding", [])))

    objective = coder.tasks[-1]["context"]["objective"]
    assert "could not be merged: src/app.py changed in the meantime" in objective
    assert "rejected by" not in objective


async def test_the_planner_is_told_the_room_files_the_proposal(team):
    """A request that says "return it as a proposal" is not a step for the agents:
    planners once required a step to present the proposal and refused the plan."""
    from jarviscore.room.work import ROOM_WORK_CONTRACT

    room, _ = team
    asked = await room.ask("Fix the app and send it as a proposal", asked_by=alice, timeout=20,
                           plan_template=plan("Fix the app", ("fix", "coding", [])))

    planned = room.redis_store.get_workflow_goal(asked.workflow_id)
    assert planned["goal"] == "Fix the app and send it as a proposal", "the method is not something asked"
    assert planned["context"]["work_method"] == ROOM_WORK_CONTRACT
    assert room.mesh._planning_brief(planned["context"]) == ROOM_WORK_CONTRACT
    started = next(e for e in room.events() if e["type"] == "ask.started")
    assert started["goal"] == "Fix the app and send it as a proposal", "the room records what was asked"


async def test_work_the_agents_could_not_plan_fails_with_the_reason(team, monkeypatch):
    room, _ = team
    mesh = room.mesh

    async def plan_fails(task, *, workflow_id, **_):
        room.redis_store.save_workflow_planning_status(
            workflow_id, "failed", error="MeshPlanError: an obligation is not covered")

    monkeypatch.setattr(mesh, "submit_goal", plan_fails)
    with pytest.raises(RuntimeError, match="could not plan this: MeshPlanError: an obligation"):
        await room.ask("Fix the app", asked_by=alice, timeout=20)

    failed = next(e for e in room.events() if e["type"] == "ask.failed")
    assert "could not plan this" in failed["error"], "not reported as a timeout"


async def test_work_that_changes_nothing_proposes_nothing(team):
    room, coder = team
    coder.execute_task = _no_edits
    asked = await room.ask("Read the code", asked_by=alice, timeout=20,
                           plan_template=plan("Read the code", ("look", "coding", [])))
    assert asked.status == "completed"
    assert asked.proposal is None


async def _no_edits(task):
    return {"status": "success", "output": "Read it; nothing to change"}


class Editor(HumanAgent):
    role = "alice"
    capabilities = ["editing"]


async def test_a_person_edits_the_files_and_their_edits_are_in_the_proposal(team, tmp_path):
    room, coder = team
    alice = Editor(agent_id="alice-1", channel=None)
    alice.poll_interval = 0.02
    alice.hitl = HITLQueue(agent_id="alice-1", inbox_dir=str(tmp_path / "hitl"))
    await alice.setup()
    # What Mesh.add + start do, for an agent joining late: register it with its
    # own one-member pool and start that pool's dispatcher.
    from jarviscore.core.pool import Pool, PoolState

    room.mesh.agents.append(alice)
    room.mesh._pools[alice.agent_id] = PoolState(
        spec=Pool(min=1, max=1), factory=None, base=alice, declared=False)
    room.mesh._distributed_worker_tasks.append(
        asyncio.create_task(room.mesh._run_pool(room.mesh._pools[alice.agent_id])))

    async def person():
        while not alice.waiting():
            await asyncio.sleep(0.02)
        [item] = alice.waiting()
        folder = Path(item["context"]["workspace"])
        assert (folder / "src" / "app.py").read_text() == "VERSION = 'v2'\n", "sees the coder's work"
        (folder / "README.md").write_text("# Repo\n\nEdited by Alice.\n")
        alice.answer(item["id"], "approved", "Tweaked the README")

    reviewer = asyncio.create_task(person())
    goal = "Fix the app and let Alice polish the docs"
    asked = await room.ask(goal, asked_by=bob, timeout=20, plan_template=plan(
        goal, ("fix", "coding", []), ("polish", "editing", ["fix"])))
    await reviewer

    assert asked.status == "completed", asked.result
    assert asked.proposal.author == "coder, alice"
    await room.accept(asked.proposal.id, by=bob)
    assert await text(room, "README.md") == "# Repo\n\nEdited by Alice.\n"
    assert await text(room, "src/app.py") == "VERSION = 'v2'\n"


class PlainFixer(CustomAgent):
    """What a developer writes: no sandbox, no overrides."""
    role = "fixer"
    capabilities = ["fixing"]

    async def execute_task(self, task):
        root = Path(task["context"]["workspace_binding"]["path"])
        (root / "plan.md").write_text("# Launch plan\n\n- Ship Tuesday\n")
        return {"status": "success", "output": "Wrote the plan"}


class PlainEditor(CustomAgent):
    role = "editor"
    capabilities = ["editing_docs"]

    async def on_peer_request(self, msg):
        root = Path(msg.data["context"]["workspace_binding"]["path"])
        plan = root / "plan.md"
        plan.write_text(plan.read_text() + "- Announce Wednesday\n")
        return "Added the announcement"


async def test_plain_custom_agents_work_in_a_room_with_no_extra_code(tmp_path, monkeypatch):
    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02})
    mesh.add(PlainFixer)
    mesh.add(PlainEditor)
    await mesh.start()
    try:
        room = Room.for_mesh(mesh, "launch", tenant="acme")
        await room.ensure({"brief.md": "# Brief\n"}, by=alice)
        goal = "Draft the launch plan and add the announcement"
        asked = await room.ask(goal, asked_by=alice, timeout=20, plan_template=plan(
            goal, ("draft", "fixing", []), ("announce", "editing_docs", ["draft"])))
        assert asked.status == "completed", asked.result
        await room.accept(asked.proposal.id, by=alice)
        assert (await room.read("plan.md")).decode() == (
            "# Launch plan\n\n- Ship Tuesday\n- Announce Wednesday\n")
    finally:
        await mesh.stop()


def test_a_custom_agent_keeps_its_own_sandbox():
    class Own(CustomAgent):
        role = "own"
        capabilities = ["x"]
        sandbox = "mine"

    assert Own().sandbox == "mine"


async def test_the_room_agent_is_reached_by_people_not_routed_work(tmp_path, monkeypatch):
    """Planners never route steps to the room's agent, so a step for a person goes to the person."""
    from jarviscore.p2p.coordinator import P2PCoordinator
    from jarviscore.room import RoomAgent

    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02})
    room_agent = mesh.add(RoomAgent)
    mesh.add(HumanAgent("team", ["approval"], channel=None))
    await mesh.start()
    try:
        catalog = mesh._mesh_capability_catalog()
        assert "approval" in catalog and "human" in catalog
        assert "room-conversation" not in catalog and "room" not in catalog
        workers = {task.get_name() for task in mesh._distributed_worker_tasks}
        assert f"distributed-worker-{room_agent.agent_id}" not in workers
        node = type("Node", (), {"agents": mesh.agents, "_get_node_id": lambda self: "node-1"})()
        payload = P2PCoordinator._capability_payload(node)
        assert room_agent.agent_id not in payload["agents"]
        assert "room-conversation" not in payload["capabilities"]
        # Nor can another agent ask it directly: it would never answer.
        team = next(a for a in mesh.agents if a is not room_agent)
        assert room_agent.agent_id not in {p["agent_id"] for p in team.peers.list_peers()}
        assert team.peers.discover(capability="room-conversation") == []
    finally:
        await mesh.stop()


# ── Whose access, restarts, stopping, and people in the middle of work ──────


class MailReader(CustomAgent):
    """Reads someone's mail through Nexus (recorded as Nexus records every call) and writes notes."""
    role = "reader"
    capabilities = ["reading_mail"]
    provider = "gmail"

    async def execute_task(self, task):
        from jarviscore.nexus.call_proxy import _record_source

        _record_source(self.provider)  # what NexusCallProxy.request does for every call
        root = Path(task["context"]["workspace_binding"]["path"])
        (root / "notes.md").write_text("From the inbox: the venue moved.\n")
        return {"status": "success", "output": "Noted the venue change"}


@pytest.fixture
async def mail_team(tmp_path, monkeypatch):
    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02,
                        "hitl_inbox_dir": str(tmp_path / "hitl")})
    reader = mesh.add(MailReader)
    await mesh.start()
    room = Room.for_mesh(mesh, "launch", tenant="acme")
    await room.ensure({"plan.md": "# Plan\n"}, by=alice)
    room.set_role(bob, "editor", by=alice)
    yield room, reader
    await mesh.stop()


def notes_plan(goal="Note what changed"):
    return plan(goal, ("read", "reading_mail", []))


async def test_work_that_used_someones_own_access_is_held_for_them(mail_team):
    room, _ = mail_team
    asked = await room.ask("Note what changed", asked_by=bob, timeout=20, plan_template=notes_plan())

    assert asked.held_for == "bob"
    assert asked.sources == [{"provider": "gmail", "person": "acme/bob"}]
    assert asked.proposal.held_for == "bob"
    assert not room.visible_to(alice, asked.proposal) and room.visible_to(bob, asked.proposal)
    finished = next(e for e in room.events() if e["type"] == "ask.finished")
    assert finished["held_for"] == "bob"
    room.release(asked.proposal.id, by=bob)
    await room.accept(asked.proposal.id, by=alice)


async def test_work_on_a_system_the_room_shares_is_not_held(mail_team):
    room, reader = mail_team
    reader.provider = "google_drive"
    room.set_shared_connectors(["google_drive"], by=alice)
    asked = await room.ask("Note what changed", asked_by=bob, timeout=20, plan_template=notes_plan())
    assert asked.held_for == "" and asked.proposal.held_for == ""


class SlowWriter(CustomAgent):
    role = "slow"
    capabilities = ["slow_writing"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.started = asyncio.Event()
        self.go = asyncio.Event()

    async def execute_task(self, task):
        self.started.set()
        await self.go.wait()
        root = Path(task["context"]["workspace_binding"]["path"])
        (root / "plan.md").write_text("# Plan\n\nWritten slowly.\n")
        return {"status": "success", "output": "Wrote it"}


@pytest.fixture
async def slow_team(tmp_path, monkeypatch):
    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02})
    writer = mesh.add(SlowWriter)
    await mesh.start()
    room = Room.for_mesh(mesh, "launch", tenant="acme")
    await room.ensure({"plan.md": "# Plan\n"}, by=alice)
    yield room, writer
    writer.go.set()
    await mesh.stop()


async def test_work_outlives_the_process_that_asked_and_is_filed_once(slow_team):
    from jarviscore.room.work import resume, unfinished

    room, writer = slow_team
    asking = asyncio.create_task(room.ask("Write the plan", asked_by=alice, workflow_id="room-launch-w1",
                                          timeout=20, plan_template=plan("Write", ("w", "slow_writing", []))))
    await asyncio.wait_for(writer.started.wait(), 10)
    asking.cancel()  # the process that asked stops
    await asyncio.gather(asking, return_exceptions=True)

    assert not room.redis_store.is_workflow_cancelled("room-launch-w1"), "the work goes on"
    assert [e["workflow_id"] for e in unfinished(room)] == ["room-launch-w1"]

    writer.go.set()
    # Two processes pick it up after the restart; it is filed once.
    results = await asyncio.gather(resume(room, room.mesh, "room-launch-w1", timeout=20),
                                   resume(room, room.mesh, "room-launch-w1", timeout=20))
    assert sum(r is not None for r in results) == 1
    kinds = [e["type"] for e in room.events()]
    assert kinds.count("proposal.opened") == 1 and kinds.count("ask.finished") == 1
    assert unfinished(room) == []


async def test_work_whose_asker_stopped_before_it_was_planned_is_still_finished(slow_team):
    from jarviscore.room.work import resume

    room, writer = slow_team
    room.note("ask.started", by="alice", by_name="Alice", goal="Write the plan",
              workflow_id="room-launch-w3", version=1)
    following = asyncio.create_task(resume(room, room.mesh, "room-launch-w3", timeout=20))
    await asyncio.sleep(0.3)
    assert not following.done(), "it waits for the plan rather than giving up"
    await room.mesh.submit_goal("Write the plan", workflow_id="room-launch-w3",
                                context={"workspace_source": {"provider": "room", "locator": room.key,
                                                              "revision": "1"},
                                         "room_id": room.key, "acting_for": "acme/alice"},
                                plan_template=plan("Write", ("w", "slow_writing", [])))
    writer.go.set()
    finished = await asyncio.wait_for(following, 20)
    assert finished.proposal is not None
    assert [e["type"] for e in room.events()].count("ask.finished") == 1


async def test_stopped_work_proposes_nothing(slow_team):
    from jarviscore.room.agent import RoomAgent

    room, writer = slow_team
    asking = asyncio.create_task(room.ask("Write the plan", asked_by=alice, workflow_id="room-launch-w2",
                                          timeout=20, plan_template=plan("Write", ("w", "slow_writing", []))))
    await asyncio.wait_for(writer.started.wait(), 10)
    with pytest.raises(PermissionError):
        RoomAgent().stop(room, "room-launch-w2", by=Person("acme", "mallory"))
    assert RoomAgent().stop(room, "room-launch-w2", by=alice, reason="wrong brief")
    writer.go.set()
    asked = await asking
    assert asked.status == "cancelled" and asked.proposal is None
    assert room.proposals() == []


class Cautious(CustomAgent):
    """Asks a person before changing anything, and goes on once they answer."""
    role = "cautious"
    capabilities = ["careful_writing"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.contexts = []

    async def execute_task(self, task):
        self.contexts.append(task["context"])
        answer = task["context"].get("hitl_resolution")
        if answer is None:
            self.hitl.request("Rewrite the whole plan?", "It changes every section.",
                              category="critical_action")
            return {"status": "waiting", "output": "Waiting for sign-off"}
        root = Path(task["context"]["workspace_binding"]["path"])
        (root / "plan.md").write_text(f"# Plan\n\nRewritten ({answer['note']}).\n")
        return {"status": "success", "output": "Rewrote it"}


async def test_work_waits_for_a_person_and_goes_on_when_they_answer(tmp_path, monkeypatch):
    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02,
                        "hitl_inbox_dir": str(tmp_path / "hitl-node")})
    cautious = mesh.add(Cautious)
    await mesh.start()
    try:
        room = Room.for_mesh(mesh, "launch", tenant="acme")
        await room.ensure({"plan.md": "# Plan\n"}, by=alice)
        asking = asyncio.create_task(room.ask(
            "Rewrite the plan", asked_by=alice, timeout=20,
            plan_template=plan("Rewrite", ("rewrite", "careful_writing", []))))

        # Another host (a chat surface) sees the question, tagged with the work it paused.
        elsewhere = HITLQueue(agent_id="surface", inbox_dir=str(tmp_path / "hitl-surface"),
                              redis_store=redis)
        for _ in range(500):
            items = elsewhere.inbox(tenant="acme")
            if items:
                break
            await asyncio.sleep(0.02)
        [item] = items
        assert item["context"]["mesh_step_id"] == "rewrite" and item["context"]["tenant"] == "acme"
        assert elsewhere.inbox(tenant="globex") == []
        await asyncio.sleep(0.2)
        assert not asking.done(), "paused for a person is not finished"

        assert elsewhere.resolve(item["id"], "approved", "yes, go ahead", by="acme/bob")
        assert not elsewhere.resolve(item["id"], "rejected", "no", by="acme/carol"), "answered once"
        asked = await asyncio.wait_for(asking, 20)

        assert asked.status == "completed", asked.result
        assert cautious.contexts[-1]["hitl_resolution"]["note"] == "yes, go ahead"
        await room.accept(asked.proposal.id, by=alice)
        assert (await room.read("plan.md")).decode() == "# Plan\n\nRewritten (yes, go ahead).\n"
    finally:
        await mesh.stop()


class Payer(CustomAgent):
    """Pays out a claim, as an integration does: the payment waits for a person's approval."""
    role = "payer"
    capabilities = ["claims_payment"]
    store = None
    paid = []

    async def execute_task(self, task):
        from jarviscore.contracts.hitl import HITLAction
        from jarviscore.control.approvals import ApprovalRequirement
        from jarviscore.kernel import approval

        context = task["context"]
        workflow, step = context["workflow_id"], context["step_id"]
        action = HITLAction(
            action_id="pay-CLM-1", tool="claimshub_pay_claim", system="claimshub",
            params={"claim_id": "CLM-1", "amount": "4000.00"},
            description="claimshub_pay_claim(claim_id=CLM-1, amount=4000.00)",
            consequence="Pays out claim CLM-1: GBP 4,000.00 to Ada Okafor.",
        )
        requirement = ApprovalRequirement(required=True, rule="deployment:claims", scopes=("claims.approve",),
                                          distinct_from=("requester",), assurance="asserted")
        waiting = approval.gate(Payer.store, workflow, step, action, requirement=requirement)
        if waiting is not None:
            return waiting
        Payer.paid.append(acting_for.get())
        result = {"status": "success", "output": "Paid CLM-1"}
        approval.settle(Payer.store, workflow, step, action.action_id, result)
        return result


@pytest.fixture
async def claims_room(tmp_path, monkeypatch):
    """A room whose work pays a claim; Carol may approve payments, Erin and Dave may not."""
    import json as _json

    from jarviscore.control import policy as policy_module
    from jarviscore.evidence import journal as journal_module

    policy = tmp_path / "policy.json"
    policy.write_text(_json.dumps({"scopes": {"grants": {"acme/carol": {"claims.approve": {"amount": "10000"}}}}}))
    monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(policy))
    monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(policy_module, "_cached", None)
    monkeypatch.setattr(journal_module, "_journal", None)
    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02,
                        "hitl_inbox_dir": str(tmp_path / "hitl")})
    mesh.add(Payer)
    Payer.store, Payer.paid = redis, []
    await mesh.start()
    room = Room.for_mesh(mesh, "claims", tenant="acme")
    carol, dave, erin = (Person("acme", n, n.title()) for n in ("carol", "dave", "erin"))
    await room.ensure({"queue.md": "# Claims\n"}, by=carol)
    for person in (dave, erin):
        room.set_role(person, "editor", by=carol)
    yield room, carol, dave, erin
    await mesh.stop()


async def test_an_action_the_rooms_work_waits_on_is_approved_in_the_room_by_who_may(claims_room):
    from jarviscore.room import APPROVE, RoomConversation
    from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent

    room, carol, dave, erin = claims_room
    surface = MemorySurface()
    conversation = RoomConversation(room, ScriptedRoomAgent(), surface, poll_interval=0.01)
    await conversation.start()
    following = asyncio.create_task(conversation.follow())
    try:
        asking = asyncio.create_task(room.ask(
            "Pay out CLM-1", asked_by=dave, timeout=20, workflow_id="room-claims-pay-1",
            plan_template=plan("Pay out CLM-1", ("pay", "claims_payment", []))))
        for _ in range(500):
            if surface.approvals:
                break
            await asyncio.sleep(0.02)
        [shown] = surface.approvals
        assert shown["title"] == "Pays out claim CLM-1: GBP 4,000.00 to Ada Okafor."
        assert shown["action"] == "claimshub_pay_claim(claim_id=CLM-1, amount=4000.00)"
        assert "claims.approve" in shown["needs"] and "not the person who asked" in shown["needs"]
        assert shown["asked_by"] == "Dave"

        await conversation.press(erin, APPROVE, shown["id"], None)
        await conversation.press(dave, APPROVE, shown["id"], None)
        refusals = [p.text for p in surface.posts if p.notice]
        assert "who holds claims.approve" in refusals[0] and "Erin" in refusals[0]
        assert "may not also approve" in refusals[1]
        await asyncio.sleep(0.2)
        assert Payer.paid == [] and not asking.done()

        await conversation.press(carol, APPROVE, shown["id"], None)
        asked = await asyncio.wait_for(asking, 20)
        assert asked.status == "completed", asked.result
        assert Payer.paid == ["acme/dave"], "paid once, for the person who asked"
        assert any(p.text.startswith("Carol approved: Pays out claim CLM-1") for p in surface.posts)
        record = room.redis_store.get_hitl_request("room-claims-pay-1", "pay", "pay-CLM-1")
        assert (record["approver"], record["assurance"]) == ("acme/carol", "asserted")
        assert record["authenticated_by"] == "surface:memory"
    finally:
        following.cancel()
        await asyncio.gather(following, return_exceptions=True)


async def test_a_declined_action_in_the_room_never_runs(claims_room):
    from jarviscore.room import DECLINE, RoomConversation
    from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent

    room, carol, dave, _ = claims_room
    surface = MemorySurface()
    conversation = RoomConversation(room, ScriptedRoomAgent(), surface, poll_interval=0.01)
    await conversation.start()
    following = asyncio.create_task(conversation.follow())
    try:
        asking = asyncio.create_task(room.ask(
            "Pay out CLM-1", asked_by=dave, timeout=20, workflow_id="room-claims-pay-2",
            plan_template=plan("Pay out CLM-1", ("pay", "claims_payment", []))))
        for _ in range(500):
            if surface.approvals:
                break
            await asyncio.sleep(0.02)
        await conversation.press(carol, DECLINE, surface.approvals[0]["id"], None)
        await asyncio.wait_for(asking, 20)
        assert Payer.paid == []
        finished = next(e for e in room.events() if e.get("type") == "ask.finished")
        assert "declined" in finished["summary"], "the room says why the work did not go ahead"
        assert any(p.text.startswith("Carol declined") for p in surface.posts)
        assert len(surface.approvals) == 1, "a decided action is not asked again"
    finally:
        following.cancel()
        await asyncio.gather(following, return_exceptions=True)


class Filer(CustomAgent):
    """Files claims in ClaimsHub with the asking person's own account, once they have connected it."""
    role = "filer"
    capabilities = ["claims_filing"]
    connected = set()
    filed = []

    async def execute_task(self, task):
        import uuid as _uuid

        person = acting_for.get()
        if person not in Filer.connected:
            return {"status": "yield", "result_id": _uuid.uuid4().hex,
                    "error": "This task needs claimshub, which is not connected here.",
                    "yield_metadata": {"yield_pending": True, "typed_outcome": "YIELD_AUTH_REQUIRED",
                                       "hitl_type": "auth", "system": "claimshub"}}
        Filer.filed.append(person)
        return {"status": "success", "output": "Filed CLM-9"}


async def test_work_needing_an_account_asks_its_person_to_connect_it_then_goes_on(tmp_path, monkeypatch):
    from jarviscore.room import RoomConversation
    from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent

    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02,
                        "hitl_inbox_dir": str(tmp_path / "hitl")})
    mesh.add(Filer)
    Filer.connected, Filer.filed = set(), []
    asked_to_connect = []

    async def connect(provider, *, on_behalf_of, return_url=None, provider_scopes=None):
        asked_to_connect.append((provider, on_behalf_of, return_url))
        return {"auth_url": f"https://nexus.example/consent?for={on_behalf_of}", "connection_id": "c1"}

    async def connected(provider, *, on_behalf_of):
        return on_behalf_of in Filer.connected

    monkeypatch.setattr(mesh, "connect", connect)
    monkeypatch.setattr(mesh, "connected", connected)
    await mesh.start()
    room = Room.for_mesh(mesh, "claims", tenant="acme")
    erin = Person("acme", "erin", "Erin")
    await room.ensure({"queue.md": "# Claims\n"}, by=alice)
    room.set_role(erin, "editor", by=alice)
    surface = MemorySurface()
    surface.connect_return_url = "https://desk.example/connected"
    conversation = RoomConversation(room, ScriptedRoomAgent(), surface, poll_interval=0.01)
    conversation.connect_check_seconds = 0.05
    await conversation.start()
    following = asyncio.create_task(conversation.follow())
    try:
        asking = asyncio.create_task(room.ask(
            "File CLM-9", asked_by=erin, timeout=20, workflow_id="room-claims-file-1",
            plan_template=plan("File CLM-9", ("file", "claims_filing", []))))
        for _ in range(500):
            if surface.connects:
                break
            await asyncio.sleep(0.02)
        [request] = surface.connects
        assert request["to"] == "erin" and request["provider"] == "claimshub"
        assert request["auth_url"] == "https://nexus.example/consent?for=acme/erin"
        assert asked_to_connect == [("claimshub", "acme/erin", "https://desk.example/connected")]
        assert not [p for p in surface.posts if "nexus.example" in p.detail and p.to != "erin"]
        await asyncio.sleep(0.3)
        assert Filer.filed == [] and not asking.done(), "nothing is done before she connects"

        Filer.connected.add("acme/erin")
        asked = await asyncio.wait_for(asking, 20)
        assert asked.status == "completed", asked.result
        assert Filer.filed == ["acme/erin"]
        assert any(p.text == "Erin connected Claimshub; the work goes on." for p in surface.posts)
        assert len(surface.connects) == 1, "asked once"
    finally:
        following.cancel()
        await asyncio.gather(following, return_exceptions=True)
        await mesh.stop()
