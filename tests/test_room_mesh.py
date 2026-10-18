"""Agents do work in a room through the real mesh, and it comes back as a proposal."""

import asyncio
from pathlib import Path

import fakeredis
import pytest

from jarviscore import Mesh
from jarviscore.auth.principal import acting_for
from jarviscore.orchestration.envelopes import DependencyAuthorization
from jarviscore.human import InboxChannel, answer_item, open_items
from jarviscore.profiles import CustomAgent
from jarviscore.human import HumanAgent
from jarviscore.room import Room
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore


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
    await mesh.start()
    room = Room.for_mesh(mesh, "repo")
    await room.ensure({"src/app.py": "VERSION = 'v1'\n", "README.md": "# Repo\n"}, by="alice")
    yield room, coder
    await mesh.stop()


async def text(room, path):
    return (await room.read(path)).decode()


async def test_agents_work_on_the_room_and_propose_their_changes(team):
    room, coder = team

    goal = "Bump the app to v2 and document it"
    asked = await room.ask(goal, asked_by="alice", timeout=20, plan_template=plan(
        goal, ("fix", "coding", []), ("docs", "docs", ["fix"])))

    assert asked.status == "completed", asked.result
    proposal = asked.proposal
    assert proposal.asked_by == "alice" and proposal.base_version == 1
    assert coder.acting_for == ["alice"], "the step ran as the person who asked"
    assert proposal.author == "coder, writer"
    assert proposal.paths == ["README.md", "src/app.py", "test_app.py"]
    assert await text(room, "src/app.py") == "VERSION = 'v1'\n", "nothing lands until accepted"

    await room.accept(proposal.id, by="bob")
    assert await text(room, "src/app.py") == "VERSION = 'v2'\n"
    assert await text(room, "README.md") == "# Repo\n\nNow at v2.\n"

    kinds = [event["type"] for event in room.events()]
    assert kinds[:2] == ["room.created", "ask.started"]
    assert kinds.count("step.claimed") == 2 and kinds.count("step.completed") == 2
    ready = next(e for e in room.events() if e["type"] == "plan.ready")
    assert [s["capability"] for s in ready["steps"]] == ["coding", "docs"]
    assert kinds.index("ask.finished") < kinds.index("proposal.accepted")
    assert kinds.index("proposal.opened") < kinds.index("ask.finished")
    finished = next(e for e in room.events() if e["type"] == "ask.finished")
    assert finished["proposal"] == proposal.id
    claimed = next(e for e in room.events() if e["type"] == "step.claimed" and e["step"] == "fix")
    assert claimed["by"] == "coder"


async def test_a_rejection_is_passed_to_the_next_attempt(team):
    room, coder = team
    first = await room.ask("Fix the app", asked_by="alice", timeout=20,
                           plan_template=plan("Fix the app", ("fix", "coding", [])))
    await room.reject(first.proposal.id, by="bob", reason="Keep the old test name")

    second = await room.ask("Fix the app", asked_by="alice", revision_of=first.proposal.id,
                            timeout=20, plan_template=plan("Fix the app", ("fix", "coding", [])))

    retry = coder.tasks[-1]["context"]
    assert retry["room"]["feedback"] == {"proposal": first.proposal.id, "decision": "rejected",
                                         "by": "bob", "reason": "Keep the old test name"}
    assert "rejected by bob: Keep the old test name" in retry["objective"]
    assert "feedback" not in coder.tasks[0]["context"]["room"]
    assert second.proposal.revision_of == first.proposal.id


async def test_work_that_changes_nothing_proposes_nothing(team):
    room, coder = team
    coder.execute_task = _no_edits
    asked = await room.ask("Read the code", asked_by="alice", timeout=20,
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
    inbox = tmp_path / "inbox"
    alice = Editor(agent_id="alice-1", channel=InboxChannel(str(inbox), poll_interval=0.02))
    await alice.setup()
    room.mesh.agents.append(alice)  # what Mesh.add + start do, for an agent joining late
    room.mesh._distributed_worker_tasks.append(
        asyncio.create_task(room.mesh._run_distributed_worker(alice)))

    async def person():
        while not open_items(str(inbox)):
            await asyncio.sleep(0.02)
        [item] = open_items(str(inbox))
        folder = Path(item["workspace"])
        assert (folder / "src" / "app.py").read_text() == "VERSION = 'v2'\n", "sees the coder's work"
        (folder / "README.md").write_text("# Repo\n\nEdited by Alice.\n")
        answer_item(item["id"], "approved", "Tweaked the README", directory=str(inbox))

    reviewer = asyncio.create_task(person())
    goal = "Fix the app and let Alice polish the docs"
    asked = await room.ask(goal, asked_by="bob", timeout=20, plan_template=plan(
        goal, ("fix", "coding", []), ("polish", "editing", ["fix"])))
    await reviewer

    assert asked.status == "completed", asked.result
    assert asked.proposal.author == "coder, alice"
    await room.accept(asked.proposal.id, by="bob")
    assert await text(room, "README.md") == "# Repo\n\nEdited by Alice.\n"
    assert await text(room, "src/app.py") == "VERSION = 'v2'\n"


def test_agents_on_unseen_nodes_are_named_by_role():
    from jarviscore.room.work import _role_of

    class Lonely:
        agents = []

    assert _role_of(Lonely, "coder-853b9765:claim") == "coder"
    assert _role_of(Lonely, "release-bot") == "release-bot"
    assert _role_of(Lonely, "") == ""


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
        room = Room.for_mesh(mesh, "launch")
        await room.ensure({"brief.md": "# Brief\n"}, by="alice")
        goal = "Draft the launch plan and add the announcement"
        asked = await room.ask(goal, asked_by="alice", timeout=20, plan_template=plan(
            goal, ("draft", "fixing", []), ("announce", "editing_docs", ["draft"])))
        assert asked.status == "completed", asked.result
        await room.accept(asked.proposal.id, by="bob")
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
