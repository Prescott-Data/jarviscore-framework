"""A room's memory: one shared, tenant-isolated memory for everyone working in
the room, the team's conversation and decisions in it, and what came from
someone's own access kept theirs."""

import asyncio

import fakeredis
import pytest

from jarviscore.kernel.kernel import Kernel
from jarviscore.memory.unified import UnifiedMemory
from jarviscore.room import Person, Room
from jarviscore.room.room import RoomPermissionError
from jarviscore.room.memory import RoomMemory
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore

alice, bob, carol = (Person("acme", n, n.title()) for n in ("alice", "bob", "carol"))


class FakeAthena:
    """Athena's scoping, as its server enforces it: a session is (tenant, user, agent);
    search covers every agent's events under one tenant and user; context is one session's."""

    def __init__(self):
        self.sessions = {}
        self.events = []

    async def get_or_create_session(self, agent_id, redis_store=None, metadata=None, *, user_id=None,
                                    tenant_id=None):
        key = (tenant_id or "default", user_id or agent_id, agent_id)
        return self.sessions.setdefault(key, f"s{len(self.sessions) + 1}")

    def _scope(self, session_id):
        return next(k for k, v in self.sessions.items() if v == session_id)

    async def write_event(self, session_id, role, event_type, content, metadata=None, **_):
        self.events.append({"session": session_id, "scope": self._scope(session_id), "role": role,
                            "type": event_type, "content": content, "metadata": dict(metadata or {})})
        return {"success": True}

    async def search_memory(self, session_id, query, limit=5, **_):
        tenant, user, _ = self._scope(session_id)
        words = {w.lower().strip("?.,") for w in query.split() if len(w) > 3}
        return [{"content": e["content"]} for e in self.events
                if e["scope"][:2] == (tenant, user) and words & {w.lower().strip("?.,") for w in e["content"].split()}
                ][:limit]

    async def get_context(self, session_id, limit=20, **_):
        return {"stm_events": [{"content": e["content"], "metadata": e["metadata"], "role": e["role"]}
                               for e in self.events if e["session"] == session_id][-limit:]}

    async def erase_memory(self, tenant_id, user_id="", agent_id=""):
        before = len(self.events)
        self.events = [e for e in self.events
                       if not (e["scope"][0] == tenant_id and (not user_id or e["scope"][1] == user_id)
                               and (not agent_id or e["scope"][2] == agent_id))]
        self.erased = getattr(self, "erased", []) + [(tenant_id, user_id, agent_id)]
        return {"success": True, "events_deleted": before - len(self.events)}

    def contents(self, tenant="acme", user=None):
        return [e["content"] for e in self.events if e["scope"][0] == tenant and (user is None or e["scope"][1] == user)]


@pytest.fixture
def athena():
    return FakeAthena()


@pytest.fixture
async def room(tmp_path, athena):
    store = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    room = Room("launch", tenant="acme", blob_storage=LocalBlobStorage(str(tmp_path)), redis_store=store)
    await room.ensure({"plan.md": "# Plan\n"}, by=alice)
    room.set_role(bob, "editor", by=alice)
    room.set_role(carol, "editor", by=alice)
    room.memory = RoomMemory(room, athena)
    return room


def memory_for(room, athena, agent, context, workflow_id="wf-1"):
    kernel = Kernel.__new__(Kernel)
    kernel.redis_store = room.redis_store
    kernel.config = {}
    target = kernel._room_memory(context, workflow_id)
    return UnifiedMemory(workflow_id, "step", agent, redis_store=room.redis_store, athena_client=athena,
                         memory_scope=target.get("memory_scope"),
                         **{k: v for k, v in target.items() if k != "memory_scope"})


def work_context(room, person):
    return {"room_id": room.key, "acting_for": person.key, "room": {"id": room.id, "tenant": room.tenant}}


class TestWhereMemoryGoes:

    def test_room_work_uses_the_rooms_tenant_and_scope_without_configuration(self, room):
        kernel = Kernel.__new__(Kernel)
        kernel.redis_store, kernel.config = room.redis_store, {}
        target = kernel._room_memory(work_context(room, bob), "wf-1")
        assert (target["memory_tenant"], target["memory_scope"], target["team_agent"]) == (
            "acme", "acme/launch", "room")
        assert target["private_scope"] == "acme/launch#private:bob"

    def test_the_rooms_conversation_has_shared_memory_only(self, room):
        kernel = Kernel.__new__(Kernel)
        kernel.redis_store, kernel.config = room.redis_store, {}
        target = kernel._room_memory({"room_id": room.key, "acting_for": alice.key}, "room-conv")
        assert "private_scope" not in target and target["memory_scope"] == "acme/launch"

    def test_work_outside_a_room_is_unchanged(self, room):
        kernel = Kernel.__new__(Kernel)
        kernel.redis_store, kernel.config = room.redis_store, {}
        assert kernel._room_memory({"acting_for": "acme/bob"}, "wf") == {}


class TestSharedAcrossTheRoom:

    async def test_what_one_agent_keeps_another_recalls_in_the_same_room_only(self, room, athena):
        writer = memory_for(room, athena, "writer-1", work_context(room, bob), "wf-1")
        assert await writer.remember("Sam owns customer support during launch week")
        await writer.close()

        coder = memory_for(room, athena, "coder-7", work_context(room, carol), "wf-2")
        assert any("Sam owns" in r["content"] for r in await coder.recall("who owns customer support"))

        other = Room("launch", tenant="globex", blob_storage=room.store.blob_storage,
                     redis_store=room.redis_store)
        stranger = memory_for(other, athena, "coder-7",
                              {"room_id": other.key, "acting_for": "globex/bob", "room": {}}, "wf-3")
        assert await stranger.recall("who owns customer support") == []

    async def test_what_the_team_said_and_decided_is_recalled_by_the_rooms_agents(self, room, athena):
        await room.memory.said(bob, "Tuesday is fixed by the board, we cannot move launch day")
        proposal = await room.propose({"plan.md": "# Plan\n\nWednesday\n"}, by=carol, title="Move launch")
        await room.reject(proposal.id, by=alice, reason="the board fixed Tuesday")
        assert await room.memory.sync() >= 2
        coder = memory_for(room, athena, "coder-7", work_context(room, carol), "wf-2")
        found = " ".join(r["content"] for r in await coder.recall("can we move the launch day"))
        assert "Bob: Tuesday is fixed by the board" in found
        assert "Alice turned down" in found and "the board fixed Tuesday" in found


class TestPrivateStaysPrivate:

    async def test_what_work_learned_from_someones_own_access_is_theirs(self, room, athena):
        room.redis_store.record_workflow_source("wf-mail", "gmail", "acme/alice")
        reader = memory_for(room, athena, "reader-1", work_context(room, alice), "wf-mail")
        assert await reader.remember("Maria's email says the Lisbon venue moved to Porto")
        await reader.close()
        assert "Maria" not in " ".join(athena.contents(user="acme/launch")), "not in the shared scope"
        assert any("Maria" in c for c in athena.contents(user="acme/launch#private:alice"))

        bobs = memory_for(room, athena, "writer-1", work_context(room, bob), "wf-bob")
        assert not any("Maria" in r["content"] for r in await bobs.recall("where is the venue for the press"))

    async def test_work_that_recalls_private_memory_is_private_work(self, room, athena):
        room.redis_store.record_workflow_source("wf-mail", "gmail", "acme/alice")
        reader = memory_for(room, athena, "reader-1", work_context(room, alice), "wf-mail")
        await reader.remember("Maria's email says the Lisbon venue moved to Porto")
        await reader.close()

        later = memory_for(room, athena, "writer-1", work_context(room, alice), "wf-later")
        found = await later.recall("where is the venue for the press")
        assert any(r.get("private") and "Maria" in r["content"] for r in found)
        assert [s["provider"] for s in room.private_sources("wf-later")] == ["memory"], \
            "so its result is held for Alice"

    async def test_shared_systems_are_shared_memory(self, room, athena):
        room.set_shared_connectors(["google_drive"], by=alice)
        room.redis_store.record_workflow_source("wf-drive", "google_drive", "acme/alice")
        reader = memory_for(room, athena, "reader-1", work_context(room, alice), "wf-drive")
        await reader.remember("The team drive's launch checklist has 12 items")
        await reader.close()
        assert any("checklist" in c for c in athena.contents(user="acme/launch"))

    async def test_held_work_is_not_in_the_teams_memory(self, room, athena):
        room.note("ask.started", by="alice", by_name="Alice", goal="summarise my inbox", workflow_id="wf-mail")
        room.note("ask.finished", by="alice", by_name="Alice", workflow_id="wf-mail", status="completed",
                  summary="Maria says the venue moved to Porto", held_for="alice")
        await room.memory.sync()
        everything = " ".join(athena.contents())
        assert "Porto" not in everything and "Alice asked the agents: summarise my inbox" in everything

    async def test_the_teams_record_is_written_once_from_where_it_left_off(self, room, athena):
        await room.memory.sync()
        before = len(athena.events)
        await room.memory.sync()
        assert len(athena.events) == before
        room.note("ask.started", by="bob", by_name="Bob", goal="tidy the plan", workflow_id="wf-9")
        assert await room.memory.sync() == 1


class TestInTheConversation:

    async def test_public_messages_and_replies_are_kept_private_ones_are_not(self, room, athena):
        from jarviscore.room import RoomConversation
        from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent

        async def answers(tools, turn):
            return "Sam owns support."

        async def private(tools, turn):
            turn.private = True
            return "Your held work found Porto."

        conversation = RoomConversation(room, ScriptedRoomAgent(answers, private), MemorySurface())
        await conversation.start()
        await conversation.hear(bob, "who owns support?", message_id="m1", addressed=True)
        await conversation.hear(alice, "what did my inbox work find?", message_id="m2", addressed=True)
        assert await room.memory.flush()
        kept = athena.contents(user="acme/launch")
        assert "Bob: who owns support?" in kept and "Sam owns support." in kept
        assert "Your held work found Porto." not in kept


    async def test_athena_being_slow_never_delays_the_conversation(self, room, athena):
        from jarviscore.room import RoomConversation
        from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent

        async def slow(*args, **kwargs):
            await asyncio.sleep(5)

        athena.write_event = slow

        async def answers(tools, turn):
            return "Here."

        conversation = RoomConversation(room, ScriptedRoomAgent(answers), MemorySurface())
        await conversation.start()
        started = asyncio.get_running_loop().time()
        await conversation.hear(bob, "status?", message_id="m1", addressed=True)
        assert asyncio.get_running_loop().time() - started < 1

    async def test_a_turn_about_someones_private_question_keeps_nothing_in_shared_memory(self, room, athena):
        from jarviscore.hitl import HITLQueue
        from jarviscore.auth.principal import act_for
        from jarviscore.room import RoomConversation
        from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent
        import tempfile

        hitl = HITLQueue(agent_id="room", inbox_dir=tempfile.mkdtemp())
        room.note("ask.started", by="alice", by_name="Alice", goal="answer Maria", workflow_id="wf-mail")
        room.redis_store.record_workflow_source("wf-mail", "gmail", "acme/alice")
        results = []

        async def tries_to_keep(tools, turn):
            results.append(turn.private)
            results.append(await tools._tool_remember("Maria offered $40k"))

        conversation = RoomConversation(room, ScriptedRoomAgent(tries_to_keep), MemorySurface())
        conversation.agent.hitl = hitl
        await conversation.start()
        with act_for("acme/alice"):
            question = hitl.request("Send Maria the $40k counter?", "From Maria's email", category="critical_action",
                                    context={"mesh_workflow_id": "wf-mail", "mesh_step_id": "s"})
        await conversation.sync()
        thread = conversation._asked[question]
        await conversation.hear(alice, "yes, but keep it quiet", thread=thread, message_id="m1")
        assert results[0] is True and results[1]["status"] == "error"
        assert "40k" not in " ".join(athena.contents(user="acme/launch"))


class TestForgetting:

    async def keep_private(self, room, athena, person, fact, workflow_id):
        room.redis_store.record_workflow_source(workflow_id, "gmail", person.key)
        mem = memory_for(room, athena, "reader", work_context(room, person), workflow_id)
        assert await mem.remember(fact)
        await mem.close()

    async def test_forgetting_a_room_erases_team_and_private_memory_even_of_people_who_left(self, room, athena):
        await room.memory.said(bob, "Tuesday is fixed by the board")
        await self.keep_private(room, athena, alice, "Maria's email says the venue moved", "wf-a")
        await self.keep_private(room, athena, bob, "Bob's calendar shows a dentist on Monday", "wf-b")
        room.set_role(bob, None, by=alice)  # bob leaves; his private memory here must still go

        totals = await room.forget(by=alice)

        assert athena.contents() == []
        assert {("acme", "acme/launch", ""), ("acme", "acme/launch#private:alice", ""),
                ("acme", "acme/launch#private:bob", "")} <= set(athena.erased)
        assert totals["events_deleted"] == 3
        assert room.redis_store.room_memory_scopes(room.key) == []
        assert any(e.get("type") == "memory_erased" for e in room.events())

    async def test_only_owners_forget_a_room(self, room):
        with pytest.raises(RoomPermissionError):
            await room.forget(by=bob)

    async def test_a_person_can_erase_their_own_private_memory_and_no_one_elses(self, room, athena):
        await self.keep_private(room, athena, alice, "Maria's email says the venue moved", "wf-a")
        await self.keep_private(room, athena, bob, "Bob's calendar shows a dentist on Monday", "wf-b")

        with pytest.raises(RoomPermissionError):
            await room.forget_person(alice, by=bob)
        await room.forget_person(bob, by=bob)

        assert not athena.contents(user="acme/launch#private:bob")
        assert athena.contents(user="acme/launch#private:alice"), "someone else's memory stays"
        await room.forget_person(alice, by=alice)
        assert not athena.contents(user="acme/launch#private:alice")

    async def test_a_room_that_keeps_no_team_memory_still_erases_local_memory(self, room, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        room.memory = None
        assert await room.forget(by=alice) == {"local_facts": 0}

    async def test_private_memory_from_before_scopes_were_recorded_is_still_erased(self, room, athena):
        await self.keep_private(room, athena, carol, "Carol's notes on the supplier", "wf-c")
        room.redis_store.forget_room_memory_scope(room.key, "acme/launch#private:carol")  # an older room

        await room.forget(by=alice)

        assert not athena.contents(user="acme/launch#private:carol"), "carol is a member, so her scope is derived"

    async def test_the_same_person_under_another_display_name_may_erase_their_own(self, room, athena):
        await self.keep_private(room, athena, bob, "Bob's calendar shows a dentist on Monday", "wf-b")
        await room.forget_person(Person("acme", "bob", ""), by=Person("acme", "bob", "Bob B."))
        assert not athena.contents(user="acme/launch#private:bob")

    async def test_nothing_private_is_written_when_its_scope_cannot_be_recorded(self, room, athena, monkeypatch):
        def broken(*_):
            raise ConnectionError("redis failover")
        monkeypatch.setattr(room.redis_store, "record_room_memory_scope", broken)
        room.redis_store.record_workflow_source("wf-x", "gmail", alice.key)
        mem = memory_for(room, athena, "reader", work_context(room, alice), "wf-x")
        assert not await mem.remember("Maria's email says the venue moved")
        assert not athena.contents(user="acme/launch#private:alice")

    async def test_queued_messages_are_erased_not_written_after(self, room, athena):
        room.memory.said_later(bob, "Tuesday is fixed by the board")
        await room.forget(by=alice)
        await room.memory.flush()
        assert athena.contents() == []

    async def test_an_erasure_waits_for_a_sync_running_elsewhere(self, room):
        assert room.redis_store.take_lease(f"{room.key}:memory", "other-process", 60)
        with pytest.raises(RuntimeError, match="retry"):
            await room.forget(by=alice)



def local_memory_for(room, agent, context, workflow_id="wf-1"):
    from jarviscore.memory.local import LocalMemory

    kernel = Kernel.__new__(Kernel)
    kernel.redis_store = room.redis_store
    kernel.config = {}
    target = kernel._room_memory(context, workflow_id)
    return UnifiedMemory(workflow_id, "step", f"{agent}-1a2b", redis_store=room.redis_store,
                         memory_scope=target.get("memory_scope"), memory_identity=agent,
                         local_memory=LocalMemory(agent, scope=target.get("memory_scope")),
                         **{k: v for k, v in target.items() if k != "memory_scope"})


class TestRoomsWithoutAthena:
    """With no Athena configured, rooms keep memory in the local store with the same rules."""

    @pytest.fixture
    def plain_room(self, room, tmp_path, monkeypatch):
        monkeypatch.delenv("ATHENA_URL", raising=False)
        monkeypatch.chdir(tmp_path)
        fresh = Room("launch", tenant="acme", blob_storage=LocalBlobStorage(str(tmp_path)),
                     redis_store=room.redis_store)
        assert fresh.memory is None
        return fresh

    async def test_what_work_learns_through_someones_own_access_stays_theirs(self, plain_room):
        plain_room.redis_store.record_workflow_source("wf-a", "gmail", alice.key)
        assert await local_memory_for(plain_room, "reader", work_context(plain_room, alice), "wf-a").remember(
            "Maria's email says the venue moved")
        assert await local_memory_for(plain_room, "reader", {"room_id": plain_room.key}, "wf-s").remember(
            "The board fixed Tuesday")

        bobs = await local_memory_for(plain_room, "reader", work_context(plain_room, bob), "wf-b").recall(
            "venue Tuesday")
        assert [item["content"] for item in bobs] == ["The board fixed Tuesday"], "alice's stays hers"

        held = []
        alices = local_memory_for(plain_room, "reader", work_context(plain_room, alice), "wf-c")
        alices._on_private_recall = lambda: held.append(True)
        found = await alices.recall("venue")
        assert any(item.get("private") and "venue" in item["content"] for item in found)
        assert held, "work that recalls private memory is private work"

    async def test_forgetting_a_room_erases_its_local_memory(self, plain_room):
        plain_room.redis_store.record_workflow_source("wf-a", "gmail", alice.key)
        await local_memory_for(plain_room, "reader", work_context(plain_room, alice), "wf-a").remember(
            "Maria's email says the venue moved")
        await local_memory_for(plain_room, "writer", {"room_id": plain_room.key}, "wf-s").remember(
            "The board fixed Tuesday")
        other = Room("other", tenant="acme", blob_storage=LocalBlobStorage("blobs"), redis_store=plain_room.redis_store)
        await local_memory_for(other, "writer", {"room_id": other.key}, "wf-o").remember("Other room's fact")

        totals = await plain_room.forget(by=alice)

        assert totals == {"local_facts": 2}
        assert not await local_memory_for(plain_room, "writer", {"room_id": plain_room.key}).recall("board Tuesday")
        assert await local_memory_for(other, "writer", {"room_id": other.key}).recall("Other room"), "other rooms stay"

    async def test_a_person_erases_their_own_local_private_memory(self, plain_room):
        for person, wf in ((alice, "wf-a"), (bob, "wf-b")):
            plain_room.redis_store.record_workflow_source(wf, "gmail", person.key)
            await local_memory_for(plain_room, "reader", work_context(plain_room, person), wf).remember(
                f"{person.id}'s private note")

        assert await plain_room.forget_person(bob, by=bob) == {"local_facts": 1}
        with pytest.raises(RoomPermissionError):
            await plain_room.forget_person(alice, by=bob)
        assert await plain_room.forget_person(alice, by=alice) == {"local_facts": 1}
