"""A room is one shared workspace that people and agents change together."""

import asyncio
import json

import fakeredis
import pytest

from jarviscore.execution.workspace import SandboxBinding
from jarviscore.room import (
    CHECKOUT_MARKER,
    Identities,
    Person,
    Room,
    RoomConflict,
    RoomPermissionError,
)
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore


alice, bob, carol, vic, mallory = (Person("acme", name, name.title())
                                   for name in ("alice", "bob", "carol", "vic", "mallory"))


@pytest.fixture
async def room(tmp_path):
    """Alice's room, with Bob and Carol as editors."""
    store = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    room = Room("launch", tenant="acme", blob_storage=LocalBlobStorage(str(tmp_path / "blobs")),
                redis_store=store)
    await room.ensure({"README.md": "# Launch\n", "src/app.py": "print('v1')\n"}, by=alice)
    room.set_role(bob, "editor", by=alice)
    room.set_role(carol, "editor", by=alice)
    return room


async def text(room, path, version=None):
    data = await room.read(path, version)
    return None if data is None else data.decode()


class TestTheHead:

    async def test_a_room_starts_at_version_one(self, room):
        head = room.head()
        assert (head.version, head.updated_by) == (1, "alice")
        assert room.members() == {"alice": "owner", "bob": "editor", "carol": "editor"}
        assert await text(room, "README.md") == "# Launch\n"
        assert [e["type"] for e in room.events()] == ["room.created", "member.changed", "member.changed"]

    async def test_ensure_does_not_recreate(self, room):
        head = await room.ensure({"other.txt": "x"}, by=bob)
        assert head.version == 1
        assert await text(room, "other.txt") is None

    async def test_an_unknown_room_says_so(self, room):
        stranger = Room("nobody", tenant="acme", blob_storage=room.store.blob_storage,
                        redis_store=room.redis_store)
        with pytest.raises(KeyError):
            stranger.head()


class TestProposing:

    async def test_a_proposal_changes_nothing_until_accepted(self, room):
        proposal = await room.propose({"README.md": "# Launch\n\nShip Tuesday.\n"},
                                      by=alice, author="writer", title="Add the date")
        assert proposal.status == "open" and proposal.base_version == 1
        assert await text(room, "README.md") == "# Launch\n"

        [change] = await room.diff(proposal.id)
        assert change.status == "modified"
        assert "+Ship Tuesday." in change.unified()

        event = room.events()[-1]
        assert (event["type"], event["author"], event["by"], event["by_name"], event["paths"]) == (
            "proposal.opened", "writer", "alice", "Alice", ["README.md"])

    async def test_proposing_what_is_already_there_is_nothing(self, room):
        assert await room.propose({"README.md": "# Launch\n"}, by=alice, author="writer") is None
        assert await room.propose({"missing.txt": None}, by=alice, author="writer") is None

    async def test_unsafe_paths_are_refused(self, room):
        with pytest.raises(ValueError):
            await room.propose({"../escape.txt": "x"}, by=alice, author="writer")


class TestAccepting:

    async def test_accepting_moves_the_head(self, room):
        proposal = await room.propose({"README.md": "v2\n", "NEW.md": "new\n"}, by=alice, author="writer")
        head = await room.accept(proposal.id, by=bob)

        assert (head.version, head.updated_by, head.proposal_id) == (2, "bob", proposal.id)
        assert await text(room, "README.md") == "v2\n"
        assert await text(room, "NEW.md") == "new\n"
        assert await text(room, "README.md", version=1) == "# Launch\n"
        assert room.proposal(proposal.id).status == "accepted"
        assert room.proposal(proposal.id).accepted_version == 2

    async def test_work_on_different_files_merges(self, room):
        readme = await room.propose({"README.md": "docs\n"}, by=alice, author="writer")
        code = await room.propose({"src/app.py": "print('v2')\n"}, by=alice, author="coder")
        await room.accept(readme.id, by=bob)
        head = await room.accept(code.id, by=bob)

        assert head.version == 3
        assert await text(room, "README.md") == "docs\n"
        assert await text(room, "src/app.py") == "print('v2')\n"
        assert room.events()[-1]["merged_over"] == 1

    async def test_the_same_edit_twice_is_not_a_conflict(self, room):
        first = await room.propose({"README.md": "same\n"}, by=alice, author="writer")
        second = await room.propose({"README.md": "same\n"}, by=alice)
        await room.accept(first.id, by=bob)
        assert (await room.accept(second.id, by=bob)).version == 3

    async def test_different_edits_to_one_file_conflict(self, room):
        mine = await room.propose({"README.md": "mine\n"}, by=alice, author="writer")
        theirs = await room.propose({"README.md": "theirs\n", "NEW.md": "x\n"}, by=alice)
        await room.accept(mine.id, by=bob)

        with pytest.raises(RoomConflict) as raised:
            await room.accept(theirs.id, by=bob)

        assert raised.value.paths == ["README.md"]
        assert await text(room, "README.md") == "mine\n"
        assert await text(room, "NEW.md") is None
        assert room.proposal(theirs.id).status == "conflicted"
        assert room.events()[-1]["type"] == "proposal.conflicted"

    async def test_deleting_a_file_someone_edited_conflicts(self, room):
        edit = await room.propose({"src/app.py": "edited\n"}, by=alice, author="coder")
        delete = await room.propose({"src/app.py": None}, by=alice)
        await room.accept(edit.id, by=bob)
        with pytest.raises(RoomConflict):
            await room.accept(delete.id, by=bob)

    async def test_a_decided_proposal_cannot_be_accepted(self, room):
        proposal = await room.propose({"README.md": "x\n"}, by=alice, author="writer")
        await room.accept(proposal.id, by=bob)
        with pytest.raises(ValueError):
            await room.accept(proposal.id, by=bob)

    async def test_racing_accepts_both_land(self, room):
        one = await room.propose({"a.txt": "a\n"}, by=alice, author="writer")
        two = await room.propose({"b.txt": "b\n"}, by=alice, author="coder")

        heads = await asyncio.gather(room.accept(one.id, by=bob), room.accept(two.id, by=carol))

        assert sorted(h.version for h in heads) == [2, 3]
        files = await room.files()
        assert files["a.txt"] == b"a\n" and files["b.txt"] == b"b\n"


class TestRevising:

    async def test_accepting_a_revision_closes_the_proposal_it_replaces(self, room):
        theirs = await room.propose({"README.md": "# Launch\n\nAgent draft.\n"}, by=alice, author="writer")
        mine = await room.propose({"README.md": "# Launch\n\nBetter.\n"}, by=carol,
                                  revision_of=theirs.id)
        await room.accept(mine.id, by=alice)
        replaced = room.proposal(theirs.id)
        assert (replaced.status, replaced.decided_by, replaced.reason) == (
            "rejected", "alice", f"replaced by {mine.id}")
        assert room.events()[-1]["type"] == "proposal.rejected"

    async def test_a_revision_leaves_an_already_decided_original_alone(self, room):
        theirs = await room.propose({"README.md": "# Launch\n\nAgent draft.\n"}, by=alice, author="writer")
        await room.reject(theirs.id, by=bob, reason="too long")
        redo = await room.propose({"README.md": "# Launch\n\nShort.\n"}, by=alice, author="writer",
                                  revision_of=theirs.id)
        await room.accept(redo.id, by=bob)
        assert room.proposal(theirs.id).reason == "too long"


class TestRejecting:

    async def test_a_rejection_keeps_its_reason(self, room):
        proposal = await room.propose({"README.md": "meh\n"}, by=alice, author="writer")
        rejected = await room.reject(proposal.id, by=bob, reason="Say what it does")

        assert (rejected.status, rejected.reason, rejected.decided_by) == (
            "rejected", "Say what it does", "bob")
        assert room.events()[-1]["reason"] == "Say what it does"
        with pytest.raises(ValueError):
            await room.reject(proposal.id, by=bob, reason="again")


class TestPeopleEditingByHand:

    async def test_checkout_edit_push(self, room, tmp_path):
        work = tmp_path / "alice"
        await room.checkout(str(work), by=alice)
        assert (work / "src" / "app.py").read_text() == "print('v1')\n"
        assert json.loads((work / CHECKOUT_MARKER).read_text())["version"] == 1

        (work / "README.md").write_text("# Launch\n\nBy hand.\n")
        (work / "notes.md").write_text("todo\n")
        (work / "src" / "app.py").unlink()
        (work / "__pycache__").mkdir()
        (work / "__pycache__" / "junk.pyc").write_bytes(b"\0")

        proposal = await room.push(str(work), by=alice, title="Edits")
        changes = {c.path: c.status for c in await room.diff(proposal.id)}
        assert changes == {"README.md": "modified", "notes.md": "added", "src/app.py": "deleted"}

    async def test_pushing_an_untouched_checkout_is_nothing(self, room, tmp_path):
        await room.checkout(str(tmp_path / "alice"), by=alice)
        assert await room.push(str(tmp_path / "alice"), by=alice) is None

    async def test_a_hand_edit_merges_with_agent_work(self, room, tmp_path):
        work = tmp_path / "alice"
        await room.checkout(str(work), by=alice)
        agent = await room.propose({"src/app.py": "print('agent')\n"}, by=alice, author="coder")
        await room.accept(agent.id, by=bob)

        (work / "README.md").write_text("alice was here\n")
        mine = await room.push(str(work), by=alice)
        head = await room.accept(mine.id, by=alice)

        assert head.version == 3
        assert await text(room, "src/app.py") == "print('agent')\n"
        assert await text(room, "README.md") == "alice was here\n"

    async def test_checkout_refuses_a_directory_with_work_in_it(self, room, tmp_path):
        (tmp_path / "busy").mkdir()
        (tmp_path / "busy" / "x").write_text("x")
        with pytest.raises(FileExistsError):
            await room.checkout(str(tmp_path / "busy"), by=alice)


class TestAgentWork:

    async def test_an_agent_workspace_delta_becomes_a_proposal(self, room):
        snapshot = await room.snapshot()
        async with SandboxBinding(room.store, snapshot) as binding:
            (binding.workspace / "src" / "app.py").write_text("print('fixed')\n")
            (binding.workspace / "test_app.py").write_text("def test(): pass\n")
            delta = await binding.export_delta("workflows/wf-1/workspace_deltas/fix")

        proposal = await room.propose_deltas([delta], base_version=1, author="coder",
                                             asked_by=alice, workflow_id="wf-1")
        assert proposal.paths == ["src/app.py", "test_app.py"]
        await room.accept(proposal.id, by=alice)
        assert await text(room, "src/app.py") == "print('fixed')\n"

    async def test_a_delta_from_another_version_is_refused(self, room):
        old = await room.snapshot()
        move = await room.propose({"README.md": "moved\n"}, by=alice, author="writer")
        await room.accept(move.id, by=bob)
        async with SandboxBinding(room.store, old) as binding:
            (binding.workspace / "README.md").write_text("late\n")
            delta = await binding.export_delta("workflows/wf-2/workspace_deltas/x")
        with pytest.raises(ValueError):
            await room.propose_deltas([delta], base_version=2, author="coder", asked_by=alice)


PLAN = "# Launch plan\n\n## Goals\nGrow signups\n\n## Dates\nShip Tuesday\n\n## Owners\nAlice\n"


class TestTwoPeopleOnOneDocument:

    async def test_edits_to_different_sections_both_land(self, room):
        setup = await room.propose({"plan.md": PLAN}, by=alice)
        await room.accept(setup.id, by=alice)
        goals = await room.propose({"plan.md": PLAN.replace("Grow signups", "Grow signups 20%")},
                                   by=alice)
        dates = await room.propose({"plan.md": PLAN.replace("Ship Tuesday", "Ship Wednesday")},
                                   by=bob)
        await room.accept(goals.id, by=alice)
        await room.accept(dates.id, by=bob)

        assert await text(room, "plan.md") == PLAN.replace(
            "Grow signups", "Grow signups 20%").replace("Ship Tuesday", "Ship Wednesday")
        assert room.events()[-1]["line_merged"] == ["plan.md"]

    async def test_different_edits_to_the_same_line_still_conflict(self, room):
        setup = await room.propose({"plan.md": PLAN}, by=alice)
        await room.accept(setup.id, by=alice)
        monday = await room.propose({"plan.md": PLAN.replace("Tuesday", "Monday")}, by=alice)
        friday = await room.propose({"plan.md": PLAN.replace("Tuesday", "Friday")}, by=bob)
        await room.accept(monday.id, by=alice)
        with pytest.raises(RoomConflict):
            await room.accept(friday.id, by=bob)


class TestParallelAgentsOnOneDocument:

    async def _branch(self, room, snapshot, name, edit):
        async with SandboxBinding(room.store, snapshot) as binding:
            path = binding.workspace / "README.md"
            path.write_text(edit(path.read_text()))
            return await binding.export_delta(f"workflows/wf/workspace_deltas/{name}")

    async def test_sections_written_in_parallel_are_combined(self, room):
        setup = await room.propose({"README.md": "# Launch\n\nIntro\n\nOutro\n"}, by=alice)
        await room.accept(setup.id, by=alice)
        snapshot = await room.snapshot()
        top = await self._branch(room, snapshot, "top", lambda t: t.replace("Intro", "Intro, by writer"))
        bottom = await self._branch(room, snapshot, "bottom", lambda t: t.replace("Outro", "Outro, by editor"))

        proposal = await room.propose_deltas([top, bottom], base_version=2, author="writer, editor", asked_by=alice)
        await room.accept(proposal.id, by=alice)

        assert await text(room, "README.md") == "# Launch\n\nIntro, by writer\n\nOutro, by editor\n"

    async def test_parallel_rewrites_of_one_line_conflict(self, room):
        snapshot = await room.snapshot()
        one = await self._branch(room, snapshot, "one", lambda t: "# One\n")
        two = await self._branch(room, snapshot, "two", lambda t: "# Two\n")
        from jarviscore.execution.workspace import WorkspaceDeltaConflict
        with pytest.raises(WorkspaceDeltaConflict):
            await room.propose_deltas([one, two], base_version=1, author="a, b", asked_by=alice)


class TestWhoCanDoWhat:

    async def test_a_room_is_private_to_its_members(self, room):
        stranger = Person("acme", "dana")
        assert room.role_of(stranger) is None
        assert not room.can(stranger, "viewer")
        with pytest.raises(RoomPermissionError, match="not a member"):
            await room.propose({"README.md": "x\n"}, by=stranger)

    async def test_opening_a_room_to_the_tenant(self, room):
        dana = Person("acme", "dana")
        room.set_visibility("tenant", by=alice, tenant_role="viewer")
        assert room.role_of(dana) == "viewer"
        with pytest.raises(RoomPermissionError):
            await room.propose({"README.md": "x\n"}, by=dana)
        assert room.role_of(Person("globex", "dana")) is None
        assert room.events()[-1]["type"] == "room.visibility"

    async def test_nobody_from_another_tenant_has_a_role(self, room):
        intruder = Person("globex", "alice")  # same id, another tenant
        assert room.role_of(intruder) is None
        with pytest.raises(RoomPermissionError):
            await room.accept("p-anything", by=intruder)
        with pytest.raises(RoomPermissionError):
            room.set_role(intruder, "editor", by=alice)

    async def test_roles_are_enforced(self, room):
        room.set_role(vic, "viewer", by=alice)
        proposal = await room.propose({"README.md": "x\n"}, by=bob)
        for person in (vic, mallory):
            with pytest.raises(RoomPermissionError, match="accept"):
                await room.accept(proposal.id, by=person)
            with pytest.raises(RoomPermissionError):
                await room.reject(proposal.id, by=person, reason="no")
            with pytest.raises(RoomPermissionError):
                await room.propose({"README.md": "mine\n"}, by=person)
        with pytest.raises(RoomPermissionError):
            room.set_role(vic, "owner", by=bob)
        await room.accept(proposal.id, by=bob)

    async def test_only_owners_change_who_sees_the_room(self, room):
        with pytest.raises(RoomPermissionError):
            room.set_visibility("tenant", by=bob)
        with pytest.raises(RoomPermissionError):
            room.set_shared_connectors(["google_drive"], by=bob)
        room.set_shared_connectors(["Google_Drive"], by=alice)
        assert room.settings()["shared_connectors"] == ["google_drive"]

    async def test_viewers_cannot_push(self, room, tmp_path):
        room.set_role(vic, "viewer", by=alice)
        await room.checkout(str(tmp_path / "vic"), by=vic)
        (tmp_path / "vic" / "README.md").write_text("mine\n")
        with pytest.raises(RoomPermissionError, match="propose"):
            await room.push(str(tmp_path / "vic"), by=vic)

    async def test_strangers_cannot_check_out(self, room, tmp_path):
        with pytest.raises(RoomPermissionError):
            await room.checkout(str(tmp_path / "m"), by=mallory)

    async def test_the_last_owner_cannot_leave(self, room):
        room.set_role(bob, "owner", by=alice)
        room.set_role(alice, None, by=bob)
        with pytest.raises(RoomPermissionError, match="at least one owner"):
            room.set_role(bob, "editor", by=bob)
        assert room.members() == {"bob": "owner", "carol": "editor"}

    async def test_unknown_roles_are_refused(self, room):
        with pytest.raises(ValueError):
            room.set_role(bob, "admin", by=alice)

    async def test_someone_removed_from_the_tenant_can_do_nothing(self, room):
        from jarviscore.room import Account, IdentityError

        people = Identities(room.redis_store)
        slack = Account("acme", "slack:T1", "U9", "Bob in Slack")
        bob_in_slack = people.person_for(slack)
        room.set_role(bob_in_slack, "editor", by=alice)
        proposal = await room.propose({"README.md": "x\n"}, by=bob_in_slack)

        people.deprovision(bob_in_slack)

        assert room.role_of(bob_in_slack) is None
        with pytest.raises(RoomPermissionError):
            await room.accept(proposal.id, by=bob_in_slack)
        # Their account is refused, rather than coming back as someone new.
        with pytest.raises(IdentityError, match="removed"):
            people.person_for(slack)


class TestTenants:

    async def test_rooms_with_one_name_in_two_tenants_are_separate(self, room):
        other = Room("launch", tenant="globex", blob_storage=room.store.blob_storage,
                     redis_store=room.redis_store)
        globex_owner = Person("globex", "alice")
        await other.ensure({"README.md": "# Globex\n"}, by=globex_owner)
        assert await text(other, "README.md") == "# Globex\n"
        assert await text(room, "README.md") == "# Launch\n"
        assert [e["type"] for e in other.events()] == ["room.created"]
        assert other.role_of(alice) is None and room.role_of(globex_owner) is None


class TestHeldWork:
    """Work that used someone's own access is theirs to share."""

    async def _held(self, room):
        snapshot = await room.snapshot()
        async with SandboxBinding(room.store, snapshot) as binding:
            (binding.workspace / "README.md").write_text("# Launch\n\nFrom Bob's inbox.\n")
            delta = await binding.export_delta("workflows/wf-mail/workspace_deltas/s")
        return await room.propose_deltas([delta], base_version=1, author="writer", asked_by=bob,
                                         workflow_id="wf-mail", held_for="bob",
                                         sources=[{"provider": "gmail", "person": "acme/bob"}])

    async def test_only_its_asker_sees_it_until_they_release_it(self, room):
        held = await self._held(room)
        assert room.visible_to(bob, held) and not room.visible_to(alice, held)
        with pytest.raises(RoomPermissionError, match="release"):
            await room.accept(held.id, by=alice)
        with pytest.raises(RoomPermissionError, match="release"):
            await room.accept(held.id, by=bob)
        with pytest.raises(RoomPermissionError):
            await room.reject(held.id, by=alice, reason="no")
        with pytest.raises(RoomPermissionError):
            room.release(held.id, by=alice)

        room.release(held.id, by=bob)

        assert room.visible_to(alice, room.proposal(held.id))
        assert room.events()[-1]["type"] == "proposal.released"
        await room.accept(held.id, by=alice)

    async def test_its_asker_can_discard_it(self, room):
        held = await self._held(room)
        await room.reject(held.id, by=bob, reason="not for the team")
        assert room.proposal(held.id).status == "rejected"

    async def test_shared_systems_are_not_private(self, room):
        room.redis_store.record_workflow_source("wf-1", "google_drive", "acme/bob")
        room.redis_store.record_workflow_source("wf-2", "gmail", "acme/bob")
        room.set_shared_connectors(["google_drive"], by=alice)
        assert room.private_sources("wf-1") == []
        assert [s["provider"] for s in room.private_sources("wf-2")] == ["gmail"]


class TestEveryDecisionIsMadeOnce:

    async def test_many_people_deciding_at_once(self, room):
        proposal = await room.propose({"README.md": "contested\n"}, by=bob)

        async def decide(i):
            try:
                if i % 2:
                    await room.accept(proposal.id, by=bob if i % 4 == 1 else alice)
                else:
                    await room.reject(proposal.id, by=carol, reason=f"no {i}")
                return "won"
            except (ValueError, RoomConflict):
                return "lost"

        outcomes = await asyncio.gather(*(decide(i) for i in range(50)))

        assert outcomes.count("won") == 1
        decisions = [e for e in room.events()
                     if e.get("proposal") == proposal.id and e["type"] != "proposal.opened"]
        assert len(decisions) == 1
        assert room.head().version == (2 if decisions[0]["type"] == "proposal.accepted" else 1)

    async def test_many_proposals_accepted_at_once_all_land(self, room):
        proposals = [await room.propose({f"notes/{i}.md": f"{i}\n"}, by=bob) for i in range(20)]
        heads = await asyncio.gather(*(room.accept(p.id, by=alice) for p in proposals))
        assert sorted(h.version for h in heads) == list(range(2, 22))
        assert len([p for p in await room.files() if p.startswith("notes/")]) == 20

    async def test_work_files_one_proposal_however_often_it_is_finished(self, room):
        snapshot = await room.snapshot()
        async with SandboxBinding(room.store, snapshot) as binding:
            (binding.workspace / "README.md").write_text("done\n")
            delta = await binding.export_delta("workflows/wf-9/workspace_deltas/s")
        first = await room.propose_deltas([delta], base_version=1, author="w", asked_by=bob,
                                          workflow_id="wf-9")
        again = await room.propose_deltas([delta], base_version=1, author="w", asked_by=bob,
                                          workflow_id="wf-9")
        assert first.id == again.id
        assert [e["type"] for e in room.events()].count("proposal.opened") == 1


class TestIdentities:

    def test_an_unlinked_account_comes_back_as_someone_new(self, room):
        from jarviscore.room import Account

        people = Identities(room.redis_store)
        account = Account("acme", "slack:T1", "U1", "u1")
        first = people.person_for(account)
        room.set_role(first, "editor", by=alice)
        anna = people.person_for(Account("acme", "app", "anna", "Anna"))
        people.complete_link(account, people.begin_link(anna))
        people.unlink(account)

        again = people.person_for(account)
        assert again.id not in (first.id, anna.id)
        assert room.role_of(again) is None, "none of the old person's roles"

    def test_a_late_name_update_cannot_undo_a_removal(self, room, monkeypatch):
        from jarviscore.room import Account, IdentityError

        people = Identities(room.redis_store)
        account = Account("acme", "slack:T1", "U2", "old name")
        person = people.person_for(account)
        read = people._person_record

        def removed_meanwhile(tenant, person_id):
            record = read(tenant, person_id)
            people.deprovision(person)       # removed between the read and the write
            return record

        monkeypatch.setattr(people, "_person_record", removed_meanwhile)
        with pytest.raises(IdentityError):
            people.person_for(Account("acme", "slack:T1", "U2", "new name"))
        monkeypatch.undo()
        assert not people.is_active(person)


class TestAudit:

    async def test_every_action_is_a_record_with_who_what_and_why(self, room):
        proposal = await room.propose({"README.md": "v2\n"}, by=bob, title="Tighter intro")
        await room.reject(proposal.id, by=carol, reason="keep it")
        room.set_shared_connectors(["google_drive"], by=alice)
        records = room.audit()
        assert [r["action"] for r in records] == [
            "room.created", "member.changed", "member.changed", "proposal.opened",
            "proposal.rejected", "room.connectors"]
        rejected = records[4]
        assert (rejected["by"], rejected["by_name"], rejected["target"], rejected["detail"]) == (
            "carol", "Carol", proposal.id, "keep it")
        assert records[-1]["detail"] == "google_drive"
        assert all(r["room"] == "acme/launch" for r in records)

    async def test_work_records_name_whose_access_it_used_and_what_it_cost(self, room):
        room.note("ask.started", by="bob", by_name="Bob", goal="read my inbox", workflow_id="wf-1")
        room.redis_store.record_workflow_source("wf-1", "gmail", "acme/bob")
        room.redis_store.reserve_workflow_tokens("wf-1", "e", "r1", 100)
        room.redis_store.settle_workflow_tokens("wf-1", "e", "r1", 80, 0.002)
        room.note("ask.finished", by="bob", by_name="Bob", workflow_id="wf-1", status="completed",
                  held_for="bob", summary="secret findings")
        started, finished = room.audit()[-2:]
        assert started["sources"] == [{"provider": "gmail", "person": "acme/bob"}]
        assert finished["usage"] == {"tokens": 80, "usd": 0.002, "calls": 1}
        assert finished["held_for"] == "bob"
        assert "secret" not in str(finished), "what private work found is not in the audit"

    async def test_a_time_window(self, room):
        import time
        cut = time.time()
        await room.propose({"README.md": "later\n"}, by=bob)
        assert [r["action"] for r in room.audit(since=cut)] == ["proposal.opened"]

    def test_identity_changes_are_logged(self, room):
        from jarviscore.room import Account

        people = Identities(room.redis_store)
        slack = Account("acme", "slack:T1", "U7", "Uma")
        uma = people.person_for(slack)
        people.complete_link(Account("acme", "app", "uma"), people.begin_link(uma))
        people.deprovision(uma)
        assert [e["action"] for e in people.log("acme")] == [
            "person.added", "account.linked", "person.removed"]
        assert people.log("globex") == []
