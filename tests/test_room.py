"""A room is one shared workspace that people and agents change together."""

import asyncio
import json

import fakeredis
import pytest

from jarviscore.execution.workspace import SandboxBinding
from jarviscore.room import (
    CHECKOUT_MARKER,
    FileRoomLedger,
    RedisRoomLedger,
    Room,
    RoomConflict,
)
from jarviscore.storage.local import LocalBlobStorage


@pytest.fixture(params=["file", "redis"])
async def room(request, tmp_path):
    ledger = (FileRoomLedger(str(tmp_path / "rooms")) if request.param == "file"
              else RedisRoomLedger(fakeredis.FakeRedis(decode_responses=True)))
    room = Room("launch", blob_storage=LocalBlobStorage(str(tmp_path / "blobs")), ledger=ledger)
    await room.ensure({"README.md": "# Launch\n", "src/app.py": "print('v1')\n"}, by="alice")
    return room


async def text(room, path, version=None):
    data = await room.read(path, version)
    return None if data is None else data.decode()


class TestTheHead:

    async def test_a_room_starts_at_version_one(self, room):
        head = room.head()
        assert (head.version, head.updated_by) == (1, "alice")
        assert await text(room, "README.md") == "# Launch\n"
        assert [e["type"] for e in room.events()] == ["room.created"]

    async def test_ensure_does_not_recreate(self, room):
        head = await room.ensure({"other.txt": "x"}, by="bob")
        assert head.version == 1
        assert await text(room, "other.txt") is None

    async def test_an_unknown_room_says_so(self, room):
        stranger = Room("nobody", blob_storage=room.store.blob_storage, ledger=room.ledger)
        with pytest.raises(KeyError):
            stranger.head()


class TestProposing:

    async def test_a_proposal_changes_nothing_until_accepted(self, room):
        proposal = await room.propose({"README.md": "# Launch\n\nShip Tuesday.\n"},
                                      author="writer", asked_by="alice", title="Add the date")
        assert proposal.status == "open" and proposal.base_version == 1
        assert await text(room, "README.md") == "# Launch\n"

        [change] = await room.diff(proposal.id)
        assert change.status == "modified"
        assert "+Ship Tuesday." in change.unified()

        event = room.events()[-1]
        assert (event["type"], event["by"], event["asked_by"], event["paths"]) == (
            "proposal.opened", "writer", "alice", ["README.md"])

    async def test_proposing_what_is_already_there_is_nothing(self, room):
        assert await room.propose({"README.md": "# Launch\n"}, author="writer") is None
        assert await room.propose({"missing.txt": None}, author="writer") is None

    async def test_unsafe_paths_are_refused(self, room):
        with pytest.raises(ValueError):
            await room.propose({"../escape.txt": "x"}, author="writer")


class TestAccepting:

    async def test_accepting_moves_the_head(self, room):
        proposal = await room.propose({"README.md": "v2\n", "NEW.md": "new\n"}, author="writer")
        head = await room.accept(proposal.id, by="bob")

        assert (head.version, head.updated_by, head.proposal_id) == (2, "bob", proposal.id)
        assert await text(room, "README.md") == "v2\n"
        assert await text(room, "NEW.md") == "new\n"
        assert await text(room, "README.md", version=1) == "# Launch\n"
        assert room.proposal(proposal.id).status == "accepted"
        assert room.proposal(proposal.id).accepted_version == 2

    async def test_work_on_different_files_merges(self, room):
        readme = await room.propose({"README.md": "docs\n"}, author="writer")
        code = await room.propose({"src/app.py": "print('v2')\n"}, author="coder")
        await room.accept(readme.id, by="bob")
        head = await room.accept(code.id, by="bob")

        assert head.version == 3
        assert await text(room, "README.md") == "docs\n"
        assert await text(room, "src/app.py") == "print('v2')\n"
        assert room.events()[-1]["merged_over"] == 1

    async def test_the_same_edit_twice_is_not_a_conflict(self, room):
        first = await room.propose({"README.md": "same\n"}, author="writer")
        second = await room.propose({"README.md": "same\n"}, author="alice")
        await room.accept(first.id, by="bob")
        assert (await room.accept(second.id, by="bob")).version == 3

    async def test_different_edits_to_one_file_conflict(self, room):
        mine = await room.propose({"README.md": "mine\n"}, author="writer")
        theirs = await room.propose({"README.md": "theirs\n", "NEW.md": "x\n"}, author="alice")
        await room.accept(mine.id, by="bob")

        with pytest.raises(RoomConflict) as raised:
            await room.accept(theirs.id, by="bob")

        assert raised.value.paths == ["README.md"]
        assert await text(room, "README.md") == "mine\n"
        assert await text(room, "NEW.md") is None
        assert room.proposal(theirs.id).status == "conflicted"
        assert room.events()[-1]["type"] == "proposal.conflicted"

    async def test_deleting_a_file_someone_edited_conflicts(self, room):
        edit = await room.propose({"src/app.py": "edited\n"}, author="coder")
        delete = await room.propose({"src/app.py": None}, author="alice")
        await room.accept(edit.id, by="bob")
        with pytest.raises(RoomConflict):
            await room.accept(delete.id, by="bob")

    async def test_a_decided_proposal_cannot_be_accepted(self, room):
        proposal = await room.propose({"README.md": "x\n"}, author="writer")
        await room.accept(proposal.id, by="bob")
        with pytest.raises(ValueError):
            await room.accept(proposal.id, by="bob")

    async def test_racing_accepts_both_land(self, room):
        one = await room.propose({"a.txt": "a\n"}, author="writer")
        two = await room.propose({"b.txt": "b\n"}, author="coder")

        heads = await asyncio.gather(room.accept(one.id, by="bob"), room.accept(two.id, by="carol"))

        assert sorted(h.version for h in heads) == [2, 3]
        files = await room.files()
        assert files["a.txt"] == b"a\n" and files["b.txt"] == b"b\n"


class TestRevising:

    async def test_accepting_a_revision_closes_the_proposal_it_replaces(self, room):
        theirs = await room.propose({"README.md": "# Launch\n\nAgent draft.\n"}, author="writer")
        mine = await room.propose({"README.md": "# Launch\n\nBetter.\n"}, author="carol",
                                  revision_of=theirs.id)
        await room.accept(mine.id, by="alice")
        replaced = room.proposal(theirs.id)
        assert (replaced.status, replaced.decided_by, replaced.reason) == (
            "rejected", "alice", f"replaced by {mine.id}")
        assert room.events()[-1]["type"] == "proposal.rejected"

    async def test_a_revision_leaves_an_already_decided_original_alone(self, room):
        theirs = await room.propose({"README.md": "# Launch\n\nAgent draft.\n"}, author="writer")
        await room.reject(theirs.id, by="bob", reason="too long")
        redo = await room.propose({"README.md": "# Launch\n\nShort.\n"}, author="writer",
                                  revision_of=theirs.id)
        await room.accept(redo.id, by="bob")
        assert room.proposal(theirs.id).reason == "too long"


class TestRejecting:

    async def test_a_rejection_keeps_its_reason(self, room):
        proposal = await room.propose({"README.md": "meh\n"}, author="writer")
        rejected = await room.reject(proposal.id, by="bob", reason="Say what it does")

        assert (rejected.status, rejected.reason, rejected.decided_by) == (
            "rejected", "Say what it does", "bob")
        assert room.events()[-1]["reason"] == "Say what it does"
        with pytest.raises(ValueError):
            await room.reject(proposal.id, by="bob", reason="again")


class TestPeopleEditingByHand:

    async def test_checkout_edit_push(self, room, tmp_path):
        work = tmp_path / "alice"
        await room.checkout(str(work))
        assert (work / "src" / "app.py").read_text() == "print('v1')\n"
        assert json.loads((work / CHECKOUT_MARKER).read_text())["version"] == 1

        (work / "README.md").write_text("# Launch\n\nBy hand.\n")
        (work / "notes.md").write_text("todo\n")
        (work / "src" / "app.py").unlink()
        (work / "__pycache__").mkdir()
        (work / "__pycache__" / "junk.pyc").write_bytes(b"\0")

        proposal = await room.push(str(work), author="alice", title="Edits")
        changes = {c.path: c.status for c in await room.diff(proposal.id)}
        assert changes == {"README.md": "modified", "notes.md": "added", "src/app.py": "deleted"}

    async def test_pushing_an_untouched_checkout_is_nothing(self, room, tmp_path):
        await room.checkout(str(tmp_path / "alice"))
        assert await room.push(str(tmp_path / "alice"), author="alice") is None

    async def test_a_hand_edit_merges_with_agent_work(self, room, tmp_path):
        work = tmp_path / "alice"
        await room.checkout(str(work))
        agent = await room.propose({"src/app.py": "print('agent')\n"}, author="coder")
        await room.accept(agent.id, by="bob")

        (work / "README.md").write_text("alice was here\n")
        mine = await room.push(str(work), author="alice")
        head = await room.accept(mine.id, by="alice")

        assert head.version == 3
        assert await text(room, "src/app.py") == "print('agent')\n"
        assert await text(room, "README.md") == "alice was here\n"

    async def test_checkout_refuses_a_directory_with_work_in_it(self, room, tmp_path):
        (tmp_path / "busy").mkdir()
        (tmp_path / "busy" / "x").write_text("x")
        with pytest.raises(FileExistsError):
            await room.checkout(str(tmp_path / "busy"))


class TestAgentWork:

    async def test_an_agent_workspace_delta_becomes_a_proposal(self, room):
        snapshot = await room.snapshot()
        async with SandboxBinding(room.store, snapshot) as binding:
            (binding.workspace / "src" / "app.py").write_text("print('fixed')\n")
            (binding.workspace / "test_app.py").write_text("def test(): pass\n")
            delta = await binding.export_delta("workflows/wf-1/workspace_deltas/fix")

        proposal = await room.propose_deltas([delta], base_version=1, author="coder",
                                             asked_by="alice", workflow_id="wf-1")
        assert proposal.paths == ["src/app.py", "test_app.py"]
        await room.accept(proposal.id, by="alice")
        assert await text(room, "src/app.py") == "print('fixed')\n"

    async def test_a_delta_from_another_version_is_refused(self, room):
        old = await room.snapshot()
        move = await room.propose({"README.md": "moved\n"}, author="writer")
        await room.accept(move.id, by="bob")
        async with SandboxBinding(room.store, old) as binding:
            (binding.workspace / "README.md").write_text("late\n")
            delta = await binding.export_delta("workflows/wf-2/workspace_deltas/x")
        with pytest.raises(ValueError):
            await room.propose_deltas([delta], base_version=2, author="coder")


PLAN = "# Launch plan\n\n## Goals\nGrow signups\n\n## Dates\nShip Tuesday\n\n## Owners\nAlice\n"


class TestTwoPeopleOnOneDocument:

    async def test_edits_to_different_sections_both_land(self, room):
        setup = await room.propose({"plan.md": PLAN}, author="alice")
        await room.accept(setup.id, by="alice")
        goals = await room.propose({"plan.md": PLAN.replace("Grow signups", "Grow signups 20%")},
                                   author="alice")
        dates = await room.propose({"plan.md": PLAN.replace("Ship Tuesday", "Ship Wednesday")},
                                   author="bob")
        await room.accept(goals.id, by="alice")
        await room.accept(dates.id, by="bob")

        assert await text(room, "plan.md") == PLAN.replace(
            "Grow signups", "Grow signups 20%").replace("Ship Tuesday", "Ship Wednesday")
        assert room.events()[-1]["line_merged"] == ["plan.md"]

    async def test_different_edits_to_the_same_line_still_conflict(self, room):
        setup = await room.propose({"plan.md": PLAN}, author="alice")
        await room.accept(setup.id, by="alice")
        monday = await room.propose({"plan.md": PLAN.replace("Tuesday", "Monday")}, author="alice")
        friday = await room.propose({"plan.md": PLAN.replace("Tuesday", "Friday")}, author="bob")
        await room.accept(monday.id, by="alice")
        with pytest.raises(RoomConflict):
            await room.accept(friday.id, by="bob")


class TestParallelAgentsOnOneDocument:

    async def _branch(self, room, snapshot, name, edit):
        async with SandboxBinding(room.store, snapshot) as binding:
            path = binding.workspace / "README.md"
            path.write_text(edit(path.read_text()))
            return await binding.export_delta(f"workflows/wf/workspace_deltas/{name}")

    async def test_sections_written_in_parallel_are_combined(self, room):
        setup = await room.propose({"README.md": "# Launch\n\nIntro\n\nOutro\n"}, author="alice")
        await room.accept(setup.id, by="alice")
        snapshot = await room.snapshot()
        top = await self._branch(room, snapshot, "top", lambda t: t.replace("Intro", "Intro, by writer"))
        bottom = await self._branch(room, snapshot, "bottom", lambda t: t.replace("Outro", "Outro, by editor"))

        proposal = await room.propose_deltas([top, bottom], base_version=2, author="writer, editor")
        await room.accept(proposal.id, by="alice")

        assert await text(room, "README.md") == "# Launch\n\nIntro, by writer\n\nOutro, by editor\n"

    async def test_parallel_rewrites_of_one_line_conflict(self, room):
        snapshot = await room.snapshot()
        one = await self._branch(room, snapshot, "one", lambda t: "# One\n")
        two = await self._branch(room, snapshot, "two", lambda t: "# Two\n")
        from jarviscore.execution.workspace import WorkspaceDeltaConflict
        with pytest.raises(WorkspaceDeltaConflict):
            await room.propose_deltas([one, two], base_version=1, author="a, b")


class TestRoles:

    async def test_a_room_is_open_until_it_has_members(self, room):
        assert room.members() == {}
        assert room.role_of("alice") == "owner"      # the creator
        assert room.role_of("anyone") == "editor"
        proposal = await room.propose({"README.md": "x\n"}, author="anyone")
        await room.accept(proposal.id, by="anyone")

    async def test_only_the_creator_makes_it_members_only_and_stays_owner(self, room):
        with pytest.raises(PermissionError):
            room.set_role("mallory", "owner", by="mallory")
        members = room.set_role("bob", "editor", by="alice")
        assert members == {"alice": "owner", "bob": "editor"}
        assert room.events()[-1]["type"] == "member.changed"

    async def test_roles_are_enforced(self, room):
        room.set_role("bob", "editor", by="alice")
        room.set_role("vic", "viewer", by="alice")
        proposal = await room.propose({"README.md": "x\n"}, author="bob")

        for person in ("vic", "stranger"):
            with pytest.raises(PermissionError, match="accept"):
                await room.accept(proposal.id, by=person)
            with pytest.raises(PermissionError):
                await room.reject(proposal.id, by=person, reason="no")
        with pytest.raises(PermissionError):
            room.set_role("vic", "owner", by="bob")
        await room.accept(proposal.id, by="bob")

    async def test_viewers_cannot_push(self, room, tmp_path):
        room.set_role("vic", "viewer", by="alice")
        await room.checkout(str(tmp_path / "vic"))
        (tmp_path / "vic" / "README.md").write_text("mine\n")
        with pytest.raises(PermissionError, match="propose"):
            await room.push(str(tmp_path / "vic"), author="vic")

    async def test_the_last_owner_cannot_leave(self, room):
        room.set_role("bob", "owner", by="alice")
        room.set_role("alice", None, by="bob")
        with pytest.raises(PermissionError, match="at least one owner"):
            room.set_role("bob", "editor", by="bob")
        assert room.members() == {"bob": "owner"}

    async def test_unknown_roles_are_refused(self, room):
        with pytest.raises(ValueError):
            room.set_role("bob", "admin", by="alice")
