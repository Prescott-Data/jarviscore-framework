"""The room's agent and conversation: people talk about the work in their own words,
the agent acts as them, and every decision is theirs to confirm."""

import asyncio
import json

import fakeredis
import pytest

from jarviscore.auth.principal import act_for, acting_for
from jarviscore.execution.workspace import SandboxBinding
from jarviscore.hitl import HITLQueue
from jarviscore.room import (
    ACCEPT, CANCEL, CONFIRM, RELEASE, SHOW_CHANGE, Person, Room, RoomConversation,
)
from jarviscore.room.agent import RoomAgent, RoomSubAgent
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore
from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent

PLAN = "# Launch plan\n\n- Announce on Tuesday\n- Email the list\n"

alice, bob, carol, dave, vic, mallory = (
    Person("acme", n, n.title()) for n in ("alice", "bob", "carol", "dave", "vic", "mallory"))


async def until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.01)


@pytest.fixture
async def room(tmp_path):
    """Alice's room; Bob, Carol and Dave edit, Vic views. Mallory is not in it."""
    store = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    room = Room("launch", tenant="acme", blob_storage=LocalBlobStorage(str(tmp_path / "blobs")),
                redis_store=store)
    await room.ensure({"plan.md": PLAN}, by=alice)
    for person in (bob, carol, dave):
        room.set_role(person, "editor", by=alice)
    room.set_role(vic, "viewer", by=alice)
    return room


class FakeMesh:
    def __init__(self):
        self.cancelled = []

    def cancel_goal(self, workflow_id, *, reason=""):
        self.cancelled.append((workflow_id, reason))
        return True


def with_agents(room, *, held=False):
    """Stand-in for the mesh's agents: they move the announcement, as a real run would."""
    asks = []

    async def ask(goal, *, asked_by, revision_of="", workflow_id="", **options):
        asks.append({"goal": goal, "asked_by": asked_by, "revision_of": revision_of,
                     "acting_for": acting_for.get()})
        head = room.head()
        who = {"by": asked_by.id, "by_name": asked_by.display}
        room.note("ask.started", **who, goal=goal, workflow_id=workflow_id, version=head.version)
        current = (await room.read("plan.md")).decode()
        changed = current.replace("Tuesday", "Wednesday")
        if held:
            snapshot = await room.snapshot()
            async with SandboxBinding(room.store, snapshot) as binding:
                (binding.workspace / "plan.md").write_text(changed)
                delta = await binding.export_delta(f"workflows/{workflow_id}/workspace_deltas/s")
            proposal = await room.propose_deltas(
                [delta], base_version=head.version, author="writer", asked_by=asked_by, title=goal,
                workflow_id=workflow_id, held_for=asked_by.id,
                sources=[{"provider": "gmail", "person": asked_by.key}])
        else:
            proposal = await room.propose(
                {"plan.md": changed}, by=asked_by, author="writer", title=goal,
                base_version=head.version, workflow_id=workflow_id, revision_of=revision_of)
        room.note("ask.finished", **who, workflow_id=workflow_id, status="completed",
                  summary="Moved it to Wednesday.", proposal=proposal.id if proposal else "",
                  held_for=asked_by.id if held else "")

    room.mesh = FakeMesh()
    room.ask = ask
    return asks


@pytest.fixture
async def following():
    """Run each conversation's follow() loop, as a surface does, for the test's duration."""
    tasks = []
    yield tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
def talk(following):
    async def start(room, *scripts, hitl=None, surface=None, follow=True):
        agent = ScriptedRoomAgent(*scripts)
        agent.hitl = hitl
        surface = surface or MemorySurface()
        conversation = RoomConversation(room, agent, surface, poll_interval=0.01)
        await conversation.start()
        if follow:
            following.append(asyncio.create_task(conversation.follow()))
        return conversation, agent, surface

    return start


async def asks_for_work(tools, turn):
    await tools._tool_ask_agents(goal="Move the announcement to Wednesday")
    return "On it."


def prepares(action, **params):
    async def script(tools, turn):
        result = await tools._tool_prepare_decision(action=action, **params)
        script.result = result
        return "Confirm it and it's done." if result["status"] == "success" else result["error"]
    return script


async def wait_for_proposal(surface, root):
    await until(lambda: any(p.proposal for p in surface.thread(root)))
    return next(p.proposal for p in surface.thread(root) if p.proposal)


class TestTheAgent:

    async def test_a_message_runs_through_the_kernel_as_the_person_with_room_memory(self, room):
        seen = {}

        class Recording(RoomAgent):
            async def execute_task(self, task):
                seen.update(task=task, acting_for=acting_for.get())
                return {"status": "success"}

        await Recording().converse(room, alice, "can we launch wednesday?", addressed=True)
        assert seen["acting_for"] == "acme/alice"
        assert seen["task"]["context"] == {"workflow_id": "room-acme--launch-conversation",
                                           "room_id": "acme/launch", "acting_for": "acme/alice",
                                           "execution_contract": {"kernel_role": "room"}}
        assert ('Handle this message from Alice, posted mentioning you:\n"""\ncan we launch wednesday?\n"""'
                in seen["task"]["task"])

    @pytest.mark.parametrize("result, quiet, posted", [
        ({"status": "success", "result_summary": "Shall I accept p-1?"}, False, ["Shall I accept p-1?"]),
        ({"status": "success", "result_summary": "That was for Bob."}, True, []),
        ({"status": "failure", "error": "lease expired"}, False,
         ["Sorry, I couldn't handle that just now. Could you say it again?"]),
    ])
    async def test_its_final_answer_is_its_reply_unless_it_stays_quiet(self, room, result, quiet, posted):
        class Answering(RoomAgent):
            async def execute_task(self, task):
                if quiet:
                    await RoomSubAgent("r", llm_client=None, room_agent=self)._tool_stay_quiet()
                return result

        turn = await Answering().converse(room, carol, "nice, I think that works?")
        assert turn.replies == posted

    def test_it_cannot_decide_for_people(self):
        tools = RoomSubAgent("room-1", llm_client=None, room_agent=RoomAgent())._tools
        assert {"ask_agents", "request_changes", "propose_version", "prepare_decision",
                "answer_question", "room_status", "running_work", "room_history", "read_file",
                "show_change", "stay_quiet"} <= set(tools)
        assert not {"accept", "reject", "release"} & set(tools)
        params = " ".join(t.description.split("Params:", 1)[-1] for t in tools.values())
        assert '"person"' not in params and '"by"' not in params, "who acts is never a parameter"

    async def test_converse_needs_an_authenticated_person(self, room):
        with pytest.raises(TypeError, match="Person who spoke"):
            await RoomAgent().converse(room, "alice", "ship it")


class TestWorking:

    async def test_a_request_becomes_a_thread_with_the_work_and_its_proposal(self, room, talk):
        asks = with_agents(room)
        conversation, agent, surface = await talk(room, asks_for_work)
        await conversation.hear(alice, "can we launch wednesday?", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")

        assert asks[0]["asked_by"] == alice and asks[0]["goal"] == "Move the announcement to Wednesday"
        assert surface.texts("m1")[0] == "On it."
        assert any("+- Announce on Wednesday" in p.code for p in surface.thread("m1") if p.proposal)
        await until(lambda: any("the agents finished" in t for t in surface.texts("m1")))
        finished = next(p for p in surface.thread("m1") if "the agents finished" in p.text)
        assert finished.detail == "Moved it to Wednesday."
        assert room.proposal(proposal).asked_by == "alice"

    async def test_feedback_redoes_the_proposal_with_the_persons_own_words(self, room, talk):
        asks = with_agents(room)

        async def feedback(tools, turn):
            assert turn.proposal, "the thread's proposal is part of the turn"
            await tools._tool_request_changes(feedback="keep the email on Monday")

        conversation, _, surface = await talk(room, asks_for_work, feedback)
        await conversation.hear(alice, "move it to wednesday", message_id="m1", addressed=True)
        first = await wait_for_proposal(surface, "m1")
        await conversation.hear(bob, "close, but the email stays on Monday", thread="m1", message_id="m2")
        await until(lambda: len(asks) == 2)

        assert room.proposal(first).status == "open", "asking for changes turns nothing down"
        assert asks[1]["revision_of"] == first and asks[1]["asked_by"] == bob
        assert '"""\nclose, but the email stays on Monday\n"""' in asks[1]["goal"]
        await until(lambda: sum(1 for p in surface.thread("m1") if p.proposal) == 2)

    async def test_a_pasted_version_is_filed_exactly_and_replaces_the_agents_when_accepted(self, room, talk):
        with_agents(room)
        mine = "# Launch plan\n\n- Announce on Thursday  \n- Email the list"

        async def files_it(tools, turn):
            assert (await tools._tool_propose_version(path="plan.md", pasted_block=1))["replaces"]

        conversation, _, surface = await talk(room, asks_for_work, files_it)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        agents = await wait_for_proposal(surface, "m1")
        await conversation.hear(bob, f"here's mine:\n```\n{mine}```", thread="m1", message_id="m2")
        bobs = next(p for p in room.proposals("open") if p.author == "Bob")
        await conversation.press(alice, ACCEPT, bobs.id, "m1")

        assert room.proposal(agents).reason == f"replaced by {bobs.id}"
        assert (await room.read("plan.md")).decode() == mine + "\n", "exactly as pasted"

    async def test_only_a_pasted_block_is_filed(self, room, talk):
        results = []

        async def tries(tools, turn):
            results.append(await tools._tool_propose_version(path="plan.md"))

        conversation, _, _ = await talk(room, tries)
        await conversation.hear(bob, "make it say Thursday", message_id="m1", addressed=True)
        assert results[0]["status"] == "error" and "paste" in results[0]["error"]
        assert room.proposals() == []

    async def test_buttons_act_directly_for_whoever_presses_them(self, room, talk):
        with_agents(room)
        conversation, _, surface = await talk(room, asks_for_work)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        await conversation.press(carol, SHOW_CHANGE, proposal, "m1")
        assert "+- Announce on Wednesday" in surface.thread("m1")[-1].code
        await conversation.press(carol, ACCEPT, proposal, "m1")
        assert room.proposal(proposal).decided_by == "carol"
        await until(lambda: any(t.startswith("✓ Carol accepted") for t in surface.texts("m1")))


class TestDecisionsAreConfirmed:

    async def test_the_agent_prepares_and_the_person_confirms(self, room, talk):
        with_agents(room)
        accept = prepares("accept")
        conversation, _, surface = await talk(room, asks_for_work, accept)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        await conversation.hear(carol, "ship it", thread="m1", message_id="m2")

        assert room.proposal(proposal).status == "open", "nothing happens from text alone"
        [decision] = surface.confirmations
        asked = next(p for p in surface.posts if p.text == decision["summary"] + "?")
        assert asked.to == "carol", "only Carol is asked"

        await conversation.press(carol, CONFIRM, decision["id"], "m1")
        assert room.head().updated_by == "carol" and room.proposal(proposal).status == "accepted"

    async def test_nobody_else_can_confirm_it_and_it_is_made_once(self, room, talk):
        with_agents(room)
        conversation, _, surface = await talk(room, asks_for_work, prepares("accept"))
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        await conversation.hear(carol, "ship it", thread="m1", message_id="m2")
        decision = surface.confirmations[0]["id"]

        await conversation.press(mallory, CONFIRM, decision, "m1")
        await conversation.press(bob, CONFIRM, decision, "m1")
        assert room.proposal(proposal).status == "open"
        assert [p.text for p in surface.posts if p.notice and p.to == "bob"] == ["Only Carol can confirm that"]

        await asyncio.gather(*(conversation.press(carol, CONFIRM, decision, "m1") for _ in range(5)))
        assert room.head().version == 2
        assert len([p for p in surface.posts if p.notice and p.to == "carol"]) == 4

    async def test_a_cancelled_or_expired_decision_does_nothing(self, room, talk):
        with_agents(room)
        conversation, _, surface = await talk(room, asks_for_work, prepares("accept"), prepares("accept"))
        conversation.decision_seconds = 1
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        await conversation.hear(carol, "ship it", thread="m1", message_id="m2")
        await conversation.press(carol, CANCEL, surface.confirmations[0]["id"], "m1")
        await conversation.press(carol, CONFIRM, surface.confirmations[0]["id"], "m1")
        await conversation.hear(carol, "actually ship it", thread="m1", message_id="m3")
        await asyncio.sleep(1.2)
        await conversation.press(carol, CONFIRM, surface.confirmations[1]["id"], "m1")
        assert room.proposal(proposal).status == "open"

    async def test_a_viewer_cannot_have_a_decision_prepared(self, room, talk):
        with_agents(room)
        accept = prepares("accept")
        conversation, _, surface = await talk(room, asks_for_work, accept)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        await wait_for_proposal(surface, "m1")
        await conversation.hear(vic, "ship it", thread="m1", message_id="m2")
        assert "Vic cannot accept proposals" in accept.result["error"]
        assert surface.confirmations == []

    async def test_rejecting_keeps_the_reason(self, room, talk):
        with_agents(room)
        reject = prepares("reject", reason="Tuesday is fixed by the board")
        conversation, _, surface = await talk(room, asks_for_work, reject)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        await conversation.hear(carol, "no, Tuesday is fixed by the board", thread="m1", message_id="m2")
        await conversation.press(carol, CONFIRM, surface.confirmations[0]["id"], "m1")
        assert room.proposal(proposal).reason == "Tuesday is fixed by the board"


class TestPermissionsOnEverySurface:

    async def test_someone_outside_a_private_room_is_told_and_nothing_runs(self, room, talk):
        conversation, agent, surface = await talk(room)  # any script call would fail: none given
        await conversation.hear(mallory, "what does plan.md say?", message_id="m1", addressed=True)
        assert agent.briefs == []
        assert surface.texts("m1") == [
            "You're not a member of the launch room, so I can't help with it. Ask one of its owners to add you."]

    async def test_a_viewer_can_look_but_not_change_anything(self, room, talk):
        with_agents(room)
        results = {}

        async def looks_and_tries(tools, turn):
            results["read"] = await tools._tool_read_file(path="plan.md")
            results["ask"] = await tools._tool_ask_agents(goal="anything")
            results["redo"] = await tools._tool_request_changes(feedback="x")

        conversation, _, surface = await talk(room, asks_for_work, looks_and_tries)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        await wait_for_proposal(surface, "m1")
        await conversation.hear(vic, "redo it", thread="m1", message_id="m2")
        assert results["read"]["status"] == "success"
        assert "Vic cannot ask for work" in results["ask"]["error"]
        assert "Vic cannot ask for changes" in results["redo"]["error"]

    async def test_buttons_hold_roles_too_and_refusals_are_private(self, room, talk):
        with_agents(room)
        conversation, _, surface = await talk(room, asks_for_work)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        await conversation.press(mallory, SHOW_CHANGE, proposal, "m1")
        await conversation.press(vic, ACCEPT, proposal, "m1")
        assert room.proposal(proposal).status == "open"
        refusals = {p.to: p.text for p in surface.posts if p.notice}
        assert "Mallory cannot" in refusals["mallory"] and "Vic cannot accept changes" in refusals["vic"]

    async def test_a_message_from_another_tenant_is_refused(self, room, talk):
        conversation, _, _ = await talk(room)
        with pytest.raises(PermissionError):
            conversation.receive(Person("globex", "alice"), "hi", message_id="m1")


class TestHeldWork:

    async def test_work_on_someones_private_access_is_shown_to_them_first(self, room, talk):
        with_agents(room, held=True)
        conversation, _, surface = await talk(room, asks_for_work)
        await conversation.hear(bob, "summarise my inbox into the plan", message_id="m1", addressed=True)
        await until(lambda: any(p.held for p in surface.posts))

        held = next(p for p in surface.posts if p.held)
        assert held.to == "bob"
        everyone = [p for p in surface.public() if p.thread == "m1"]
        assert not any(p.proposal or "Wednesday" in p.code or "Moved it" in p.detail for p in everyone)
        assert any("used Bob's private access" in p.text for p in everyone)

        await conversation.press(bob, RELEASE, held.proposal, "m1")
        await until(lambda: any(p.proposal == held.proposal for p in surface.public()))
        await conversation.press(alice, ACCEPT, held.proposal, "m1")
        assert room.proposal(held.proposal).status == "accepted"

    async def test_others_cannot_see_or_release_it(self, room, talk):
        with_agents(room, held=True)
        conversation, _, surface = await talk(room, asks_for_work)
        await conversation.hear(bob, "summarise my inbox", message_id="m1", addressed=True)
        await until(lambda: any(p.held for p in surface.posts))
        held = next(p for p in surface.posts if p.held).proposal
        await conversation.press(alice, SHOW_CHANGE, held, "m1")
        await conversation.press(alice, RELEASE, held, "m1")
        assert room.proposal(held).held_for == "bob"
        assert not any(p.code and p.to == "alice" for p in surface.posts)


class TestWhoIsWatching:

    async def test_nothing_is_posted_where_someone_may_not_see_the_room(self, room, talk):
        with_agents(room)
        surface = MemorySurface()
        surface.audience_problem = "Mallory is in this channel but not in the room"
        conversation, agent, _ = await talk(room, asks_for_work, surface=surface)
        conversation.audience_seconds = 0
        room.note("ask.started", by="dave", by_name="Dave", goal="tidy", workflow_id="wf-x")
        await asyncio.sleep(0.1)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)

        assert agent.briefs == [], "the agent does not work where the room may not be seen"
        public = [p.text for p in surface.public()]
        assert public == ["I've stopped posting the launch room here: "
                          "Mallory is in this channel but not in the room."]

        surface.audience_problem = None
        await until(lambda: any("Dave asked: tidy" in p.text for p in surface.public()))
        assert "carrying on" in surface.public()[1].text

    async def test_a_room_change_is_checked_before_anything_else_is_posted(self, room, talk):
        surface = MemorySurface()
        conversation, _, _ = await talk(room, surface=surface)
        room.set_role(carol, None, by=alice)
        surface.audience_problem = "Carol is in this channel but not in the room"
        room.note("ask.started", by="dave", by_name="Dave", goal="secret plan", workflow_id="wf-y")
        await asyncio.sleep(0.2)
        assert not any("secret plan" in p.text for p in surface.posts)


class TestDelivery:

    async def test_a_failed_post_is_retried_and_nothing_is_lost_or_doubled(self, room, talk):
        surface = MemorySurface()
        conversation, _, _ = await talk(room, surface=surface)
        surface.fail_next = 3
        for i in range(5):
            room.note("ask.started", by="dave", by_name="Dave", goal=f"task {i}", workflow_id=f"wf-{i}")
        await until(lambda: sum("Dave asked" in p.text for p in surface.posts) == 5)
        await asyncio.sleep(0.1)
        lines = [p.text for p in surface.posts if "Dave asked" in p.text]
        assert lines == [f"Dave asked: task {i}" for i in range(5)]

    async def test_two_processes_on_one_surface_post_each_update_once(self, room, talk):
        surface = MemorySurface()
        await talk(room, surface=surface)
        await talk(room, surface=surface)
        for i in range(10):
            room.note("ask.started", by="dave", by_name="Dave", goal=f"task {i}", workflow_id=f"wf-{i}")
        await until(lambda: sum("Dave asked" in p.text for p in surface.posts) == 10)
        await asyncio.sleep(0.2)
        assert sum("Dave asked" in p.text for p in surface.posts) == 10

    async def test_a_message_received_before_a_restart_is_handled_after_it(self, room, talk):
        replies = []

        async def answers(tools, turn):
            replies.append(turn.message)
            return "Here's the plan."

        first, _, surface = await talk(room, follow=False)
        assert first.receive(bob, "what's the plan?", message_id="m1", addressed=True)
        assert not first.receive(bob, "what's the plan?", message_id="m1", addressed=True), "redelivery"
        # The process stops before handling it. The next one picks it up.
        second = RoomConversation(room, ScriptedRoomAgent(answers), surface)
        await second.start()
        await until(lambda: replies == ["what's the plan?"])
        await until(lambda: "Here's the plan." in surface.texts("m1"))
        await second.handle("m1")
        assert replies == ["what's the plan?"], "handled once"

    async def test_a_message_handled_again_after_a_crash_repeats_nothing(self, room, talk):
        asks = with_agents(room)
        pasted = "# Launch plan\n\n- Announce on Friday\n"

        async def acts(tools, turn):
            await tools._tool_ask_agents(goal="Move the announcement")
            await tools._tool_propose_version(path="plan.md", pasted_block=1)
            return "On it."

        first, _, surface = await talk(room, acts, acts, follow=False)
        message = f"move it, or use mine:\n```\n{pasted}```"
        first.receive(bob, message, message_id="m1", addressed=True)
        await first.handle("m1")
        await until(lambda: len(asks) == 1)
        # The process stopped after acting but before the message was marked handled.
        raw = json.loads(room.redis_store._redis.hget(
            room.redis_store._conv_key(room.key, surface.key, "inbound"), "m1"))
        room.redis_store._redis.hset(room.redis_store._conv_key(room.key, surface.key, "inbound"), "m1",
                                     json.dumps({**raw, "status": "pending"}))

        second = RoomConversation(room, first.agent, surface)
        await second.start()
        await until(lambda: not room.redis_store.pending_messages(room.key, surface.key))
        await asyncio.sleep(0.1)

        assert len(asks) == 1, "the work was not started again"
        assert len([p for p in room.proposals() if p.author == "Bob"]) == 1, "the version was filed once"

    async def test_messages_in_one_thread_are_handled_in_order(self, room, talk):
        order = []

        def records(n):
            async def script(tools, turn):
                order.append(turn.message)
                await asyncio.sleep(0.05 if n == 0 else 0)
            return script

        conversation, _, _ = await talk(room, *(records(n) for n in range(3)))
        await conversation.hear(bob, "one", message_id="m1", addressed=True)
        conversation._remember("threads", "wf:x", "m1")
        conversation.receive(bob, "two", message_id="m2", thread="m1")
        conversation.receive(bob, "three", message_id="m3", thread="m1")
        # The later message's handler starts first: it still waits its turn.
        await asyncio.gather(conversation.handle("m3"), conversation.handle("m2"))
        assert order == ["one", "two", "three"]


class TestWhatTheReviewFound:
    """Regression tests for gaps an independent review found."""

    async def test_replies_about_held_work_go_to_its_asker_alone(self, room, talk):
        with_agents(room, held=True)

        async def shows(tools, turn):
            await tools._tool_show_change()
            return "It adds the venue change from your inbox."

        conversation, _, surface = await talk(room, asks_for_work, shows)
        await conversation.hear(bob, "summarise my inbox", message_id="m1", addressed=True)
        await until(lambda: any(p.held for p in surface.posts))
        await conversation.hear(bob, "what did it find?", thread="m1", message_id="m2")
        reply = next(p for p in surface.posts if p.text == "It adds the venue change from your inbox.")
        assert reply.to == "bob"

    async def test_a_question_from_private_work_is_not_shown_to_others(self, room, talk, tmp_path):
        with_agents(room, held=True)
        hitl = HITLQueue(agent_id="room", inbox_dir=str(tmp_path / "hitl"))

        async def looks(tools, turn):
            looks.questions = turn.questions

        conversation, _, surface = await talk(room, asks_for_work, looks, hitl=hitl)
        await conversation.hear(bob, "summarise my inbox", message_id="m1", addressed=True)
        await until(lambda: any(p.held for p in surface.posts))
        workflow = next(k[3:] for k in conversation._threads if k.startswith("wf:"))
        room.redis_store.record_workflow_source(workflow, "gmail", "acme/bob")
        with act_for("acme/bob"):
            hitl.assign("Is the Lisbon venue confirmed per Maria's email?", "x", targets=["team"],
                        context={"workflow_id": workflow})
        await until(lambda: any("need someone" in p.text for p in surface.posts))
        await conversation.hear(carol, "anything I can help with?", thread="m1", message_id="m2")
        assert "Lisbon" not in json.dumps(looks.questions)

    async def test_full_change_is_private_while_the_room_is_paused_here(self, room, talk):
        with_agents(room)
        surface = MemorySurface()
        conversation, _, _ = await talk(room, asks_for_work, surface=surface)
        conversation.audience_seconds = 0
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        surface.audience_problem = "Mallory is in this channel but not in the room"
        await conversation.press(alice, SHOW_CHANGE, proposal, "m1")
        shown = [p for p in surface.posts if p.text.startswith("The full change")]
        assert shown and all(p.to == "alice" for p in shown)

    async def test_an_update_the_surface_keeps_refusing_does_not_block_the_rest(self, room, talk):
        surface = MemorySurface()
        conversation, _, _ = await talk(room, surface=surface)
        conversation.max_post_failures = 3
        surface.fail_next = 3
        for i in range(3):
            room.note("ask.started", by="dave", by_name="Dave", goal=f"task {i}", workflow_id=f"wf-{i}")
        await until(lambda: sum("Dave asked" in p.text for p in surface.posts) == 2)
        assert [p.text for p in surface.posts if "Dave asked" in p.text] == [
            "Dave asked: task 1", "Dave asked: task 2"]

    async def test_answers_only_reach_this_rooms_questions(self, room, talk, tmp_path):
        hitl = HITLQueue(agent_id="room", inbox_dir=str(tmp_path / "hitl"))
        conversation, _, _ = await talk(room, hitl=hitl)
        with act_for("acme/alice"):
            other = hitl.assign("Another room's question", "x", targets=["team"],
                                context={"workflow_id": "room-elsewhere-1"})
        with pytest.raises(PermissionError):
            await conversation.answer_now(bob, other, "yes", None)
        assert hitl.check(other) is None

    async def test_numeric_person_ids_survive_the_history(self, room):
        numeric = Person("acme", "42", "Forty-Two")
        room.set_role(numeric, "editor", by=alice)
        room.note("ask.started", by=numeric.id, by_name=numeric.display, goal="x", workflow_id="wf-42")
        [running] = RoomAgent.running_work(room)
        assert running["asked_by"] == "42"


class TestListening:

    async def test_only_messages_for_the_room_reach_the_agent(self, room, talk):
        conversation, agent, _ = await talk(room)  # any call would fail: no scripts
        await conversation.hear(bob, "lunch anyone?", message_id="x1")
        await conversation.hear(bob, "agreed", thread="someone-elses-thread", message_id="x2")
        assert agent.briefs == []

    async def test_the_agent_sees_the_thread(self, room, talk):
        with_agents(room)

        async def stays_quiet(tools, turn):
            await tools._tool_stay_quiet()
            return "Not for me."

        conversation, agent, surface = await talk(room, asks_for_work, stays_quiet)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        before = len(surface.posts)
        await conversation.hear(bob, "@carol are you around tomorrow?", thread="m1", message_id="m2")

        assert len(surface.posts) == before, "nothing said when the agent stays quiet"
        brief = agent.briefs[-1]
        assert "in a thread you are part of" in brief
        assert f'"id": "{proposal}"' in brief and '"thread_so_far"' in brief and "move it" in brief


class TestSteering:

    async def test_work_in_progress_can_be_stopped_by_its_asker(self, room, talk):
        room.mesh = FakeMesh()
        room.note("ask.started", by="bob", by_name="Bob", goal="rewrite everything", workflow_id="wf-big")
        stop = prepares("stop", reason="wrong brief")

        async def lists(tools, turn):
            listed = await tools._tool_running_work()
            assert [w["workflow_id"] for w in listed["running"]] == ["wf-big"]

        conversation, _, surface = await talk(room, lists, stop)
        await conversation.hear(bob, "what's running?", message_id="m1", addressed=True)
        await conversation.hear(bob, "stop that, wrong brief", message_id="m2", addressed=True)
        await conversation.press(bob, CONFIRM, surface.confirmations[0]["id"], "m2")
        assert room.mesh.cancelled == [("wf-big", "Bob: wrong brief")]

    async def test_only_the_asker_or_an_owner_stops_work(self, room, talk):
        room.mesh = FakeMesh()
        room.note("ask.started", by="bob", by_name="Bob", goal="rewrite", workflow_id="wf-big")
        stop = prepares("stop")
        conversation, _, _ = await talk(room, stop, prepares("stop"))
        await conversation.hear(carol, "stop it", message_id="m1", addressed=True)
        assert "Carol cannot stop work someone else asked for" in stop.result["error"]
        await conversation.hear(alice, "stop it", message_id="m2", addressed=True)
        assert room.mesh.cancelled == []  # prepared, not yet confirmed


class TestAgentsAskingPeople:

    async def _work(self, room, conversation, surface):
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        await wait_for_proposal(surface, "m1")
        return next(k[3:] for k in conversation._threads if k.startswith("wf:"))

    async def test_a_question_is_asked_in_the_work_thread_and_answered_in_their_words(
            self, room, talk, tmp_path):
        with_agents(room)
        hitl = HITLQueue(agent_id="room", inbox_dir=str(tmp_path / "hitl"))

        async def answers_it(tools, turn):
            [question] = turn.questions
            answers_it.result = await tools._tool_answer_question(question=question["id"])

        conversation, agent, surface = await talk(room, asks_for_work, answers_it, hitl=hitl)
        workflow = await self._work(room, conversation, surface)
        with act_for("acme/alice"):  # as the room's work runs: for the person who asked
            item = hitl.assign("Which date should we announce?", "Which date?", targets=["team"],
                               context={"workflow_id": workflow, "upstream": {"draft": "Tuesday clashes"}})
        await until(lambda: any("The agents need someone" in p.text for p in surface.thread("m1")))
        question = next(p for p in surface.thread("m1") if "The agents need someone" in p.text)
        assert "Which date should we announce?" in question.text and "Tuesday clashes" in question.detail

        await conversation.hear(bob, "Wednesday the 14th works", thread="m1", message_id="m2")
        resolution = hitl.check(item)
        assert (resolution.note, resolution.resolved_by) == ("Wednesday the 14th works", "acme/bob")
        assert "questions_from_the_agents_waiting_for_people_here" in agent.briefs[-1]

    async def test_sign_off_is_a_decision_the_person_confirms(self, room, talk, tmp_path):
        with_agents(room)
        hitl = HITLQueue(agent_id="room", inbox_dir=str(tmp_path / "hitl"))

        async def tries_to_answer(tools, turn):
            tries_to_answer.result = await tools._tool_answer_question(question=turn.questions[0]["id"])

        async def approves(tools, turn):
            await tools._tool_prepare_decision(action="approve", target=turn.questions[0]["id"])

        conversation, _, surface = await talk(room, asks_for_work, tries_to_answer, approves, hitl=hitl)
        workflow = await self._work(room, conversation, surface)
        with act_for("acme/alice"):
            item = hitl.request("Send the announcement email?", "To 40k people.", category="critical_action",
                                context={"mesh_workflow_id": workflow, "mesh_step_id": "send"})
        await until(lambda: any("need sign-off" in p.text for p in surface.thread("m1")))
        await conversation.hear(carol, "yes send it", thread="m1", message_id="m2")
        assert "decision" in tries_to_answer.result["error"] and hitl.check(item) is None

        await conversation.hear(carol, "yes, send it", thread="m1", message_id="m3")
        await conversation.press(carol, CONFIRM, surface.confirmations[0]["id"], "m1")
        assert hitl.check(item).is_approved and hitl.check(item).resolved_by == "acme/carol"

    async def test_questions_from_other_rooms_and_tenants_stay_there(self, room, talk, tmp_path):
        with_agents(room)
        hitl = HITLQueue(agent_id="room", inbox_dir=str(tmp_path / "hitl"))
        conversation, _, surface = await talk(room, asks_for_work, hitl=hitl)
        await self._work(room, conversation, surface)
        workflow = next(k[3:] for k in conversation._threads if k.startswith("wf:"))
        with act_for("globex/alice"):  # this room's workflow id, but raised for another tenant
            hitl.assign("Globex's secret", "x", targets=["team"], context={"workflow_id": workflow})
        with act_for("acme/alice"):
            hitl.assign("Another room's secret", "x", targets=["team"],
                        context={"workflow_id": "room-elsewhere-1"})
        await asyncio.sleep(0.1)
        assert not any("secret" in p.text for p in surface.posts)


class TestRemembering:

    async def test_the_room_remembers_what_was_decided_and_why(self, room, talk):
        with_agents(room)
        seen = []

        async def recalls(tools, turn):
            seen.append((await tools._tool_room_history())["history"])
            return "Carol turned it down: Tuesday is fixed by the board."

        conversation, _, surface = await talk(room, asks_for_work, recalls)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        await room.reject(proposal, by=carol, reason="Tuesday is fixed by the board")
        await conversation.hear(dave, "why didn't we move the launch?", message_id="m3", addressed=True)
        assert any("✗ Carol rejected" in line and "Tuesday is fixed by the board" in line for line in seen[0])
        assert surface.texts("m3")[-1] == "Carol turned it down: Tuesday is fixed by the board."

    async def test_a_restart_keeps_the_threads_and_does_not_greet_again(self, room, talk):
        with_agents(room)
        conversation, _, surface = await talk(room, asks_for_work)
        await conversation.hear(alice, "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")

        async def knows_the_thread(tools, turn):
            assert turn.proposal == proposal
            return "Still here."

        again = RoomConversation(room, ScriptedRoomAgent(knows_the_thread), surface)
        await again.start()
        assert len([p for p in surface.posts if p.thread is None and not p.to]) == 1
        await again.hear(bob, "you there?", thread="m1", message_id="m9")
        assert "Still here." in surface.texts("m1")

    async def test_work_started_anywhere_else_gets_its_own_thread(self, room, talk):
        conversation, _, surface = await talk(room)
        room.note("ask.started", by="dave", by_name="Dave", goal="tidy the plan", workflow_id="wf-cli")
        pushed = await room.propose({"plan.md": PLAN + "- Post on LinkedIn\n"}, by=dave)
        await until(lambda: any(p.proposal == pushed.id for p in surface.posts))
        top = [p for p in surface.posts if p.thread is None]
        assert "Dave asked: tidy the plan" in top[1].text
        assert top[2].proposal == pushed.id


async def test_scripts_call_tools_by_the_names_the_model_uses(room):
    """The guide's test calls tools.prepare_decision(...), as the model names it."""
    from jarviscore.testing.rooms import RoomTools
    from jarviscore.room.agent import RoomSubAgent

    tools = RoomTools(RoomSubAgent("room-1", llm_client=None, room_agent=ScriptedRoomAgent()))
    assert tools.prepare_decision == tools._subagent._tool_prepare_decision
    assert tools.ask_agents == tools._subagent._tool_ask_agents


def test_replies_reach_people_without_the_runtimes_receipt_ids():
    """Live: a reply ended with 'Tool receipt: tool:room-acme--launch-conversation: step_…:1'."""
    from jarviscore.room.agent import for_people

    reply = ("I prepared acceptance of proposal p-28df0d4e for announcement.md. Confirm it with "
             "one tap. Tool receipt: tool:room-acme--launch-conversation: step_1792742613_4624fc40 :1")
    assert for_people(reply) == (
        "I prepared acceptance of proposal p-28df0d4e for announcement.md. Confirm it with one tap.")
    assert for_people("Done (receipt tool:wf-1:step-2:3). p-1a2b3c4d is in the thread.") == (
        "Done. p-1a2b3c4d is in the thread.")
    assert for_people("The receipts show nothing odd.") == "The receipts show nothing odd."
