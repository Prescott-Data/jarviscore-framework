"""The room's agent: people talk about the work in their own words and it acts as them."""

import asyncio

import fakeredis
import pytest

from jarviscore.auth.principal import acting_for
from jarviscore.hitl import HITLQueue
from jarviscore.room import Room
from jarviscore.room.agent import RoomAgent, RoomSubAgent
from jarviscore.room.conversation import ACCEPT, SHOW_CHANGE, RoomConversation
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore
from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent

PLAN = "# Launch plan\n\n- Announce on Tuesday\n- Email the list\n"


async def until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.01)


@pytest.fixture
async def room(tmp_path):
    store = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    room = Room("launch", blob_storage=LocalBlobStorage(str(tmp_path / "blobs")), redis_store=store)
    await room.ensure({"plan.md": PLAN}, by="alice")
    return room


def with_agents(room):
    """Stand-in for the mesh's agents: they move the announcement, as a real run would."""
    asks = []

    async def ask(goal, *, asked_by, revision_of="", workflow_id="", **options):
        asks.append({"goal": goal, "asked_by": asked_by, "revision_of": revision_of,
                     "acting_for": acting_for.get()})
        head = room.head()
        room.note("ask.started", by=asked_by, goal=goal, workflow_id=workflow_id, version=head.version)
        current = (await room.read("plan.md")).decode()
        proposal = await room.propose(
            {"plan.md": current.replace("Tuesday", "Wednesday")}, author="writer", asked_by=asked_by,
            title=goal, base_version=head.version, workflow_id=workflow_id, revision_of=revision_of)
        room.note("ask.finished", by=asked_by, workflow_id=workflow_id, status="completed",
                  summary="Moved it to Wednesday.", proposal=proposal.id if proposal else "")

    room.mesh = object()
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
    async def start(room, *scripts, people=None, hitl=None, surface=None):
        agent = ScriptedRoomAgent(*scripts)
        agent.hitl = hitl
        surface = surface or MemorySurface()
        conversation = RoomConversation(room, agent, surface, people=people, poll_interval=0.01)
        await conversation.start()
        following.append(asyncio.create_task(conversation.follow()))
        return conversation, agent, surface

    return start


async def asks_for_work(tools, turn):
    await tools._tool_ask_agents(goal="Move the announcement to Wednesday")
    return "On it."


async def wait_for_proposal(surface, root):
    await until(lambda: any(p.proposal for p in surface.thread(root)))
    return next(p.proposal for p in surface.thread(root) if p.proposal)


class TestTheAgent:

    async def test_a_message_runs_through_the_kernel_as_the_person_with_room_memory(self, room, talk):
        seen = {}

        class Recording(RoomAgent):
            async def execute_task(self, task):
                seen.update(task=task, acting_for=acting_for.get())
                return {"status": "success"}

        await Recording().converse(room, "alice", "can we launch wednesday?", addressed=True)
        assert seen["acting_for"] == "alice"
        assert seen["task"]["context"] == {
            "workflow_id": "room-launch-conversation", "room_id": "launch", "acting_for": "alice"}
        assert 'Handle this message from alice, posted mentioning you:\n"""\ncan we launch wednesday?\n"""' in seen["task"]["task"]

    @pytest.mark.parametrize("result, quiet, posted", [
        ({"status": "success", "result_summary": "Do you want me to accept p-1?"}, False,
         ["Do you want me to accept p-1?"]),
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

        turn = await Answering().converse(room, "carol", "nice, I think that works?")
        assert turn.replies == posted

    def test_the_room_role_is_a_kernel_role_with_its_own_tools(self):
        tools = RoomSubAgent("room-1", llm_client=None, room_agent=RoomAgent())._tools
        assert {"ask_agents", "request_changes", "accept", "reject", "propose_version",
                "answer_question", "room_status", "read_file", "show_change", "stay_quiet"} <= set(tools)
        assert "person" not in tools["accept"].description, "who acts is never a parameter"


class TestWorking:

    async def test_a_request_becomes_a_thread_with_the_work_and_its_proposal(self, room, talk):
        asks = with_agents(room)
        conversation, agent, surface = await talk(room, asks_for_work)
        await conversation.hear("alice", "can we launch wednesday?", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")

        assert asks[0]["asked_by"] == "alice" and asks[0]["goal"] == "Move the announcement to Wednesday"
        texts = surface.texts("m1")
        assert texts[0] == "On it."
        assert any("+- Announce on Wednesday" in p.code for p in surface.thread("m1") if p.proposal)
        await conversation.sync()
        finished = next(p for p in surface.thread("m1") if "the agents finished" in p.text)
        assert finished.detail == "Moved it to Wednesday."
        assert room.proposal(proposal).asked_by == "alice"

    async def test_feedback_redoes_the_proposal_with_the_persons_words(self, room, talk):
        asks = with_agents(room)

        async def feedback(tools, turn):
            assert turn.proposal, "the thread's proposal is part of the turn"
            await tools._tool_request_changes(feedback="Keep the email on Monday")

        conversation, _, surface = await talk(room, asks_for_work, feedback)
        await conversation.hear("alice", "move it to wednesday", message_id="m1", addressed=True)
        first = await wait_for_proposal(surface, "m1")
        await conversation.hear("bob", "close, but the email stays on Monday", thread="m1", message_id="m2")
        await until(lambda: len(asks) == 2)

        assert room.proposal(first).reason == "Keep the email on Monday"
        assert room.proposal(first).decided_by == "bob"
        assert asks[1]["revision_of"] == first and asks[1]["asked_by"] == "bob"
        await until(lambda: sum(1 for p in surface.thread("m1") if p.proposal) == 2)

    async def test_a_decision_is_taken_as_the_person_who_spoke(self, room, talk):
        with_agents(room)

        async def accepts(tools, turn):
            await tools._tool_accept()
            return "Accepted."

        conversation, _, surface = await talk(room, asks_for_work, accepts)
        await conversation.hear("alice", "move it", message_id="m1", addressed=True)
        await wait_for_proposal(surface, "m1")
        await conversation.hear("carol", "ship it", thread="m1", message_id="m2")
        assert room.head().version == 2 and room.head().updated_by == "carol"
        assert any(t.startswith("✓ carol accepted") for t in surface.texts("m1"))

    async def test_roles_hold_and_the_refusal_reaches_the_person(self, room, talk):
        with_agents(room)
        results = []

        async def tries_to_accept(tools, turn):
            results.append(await tools._tool_accept())

        room.set_role("bob", "viewer", by="alice")
        conversation, _, surface = await talk(room, asks_for_work, tries_to_accept)
        await conversation.hear("alice", "move it", message_id="m1", addressed=True)
        await wait_for_proposal(surface, "m1")
        await conversation.hear("bob", "ship it", thread="m1", message_id="m2")
        assert results[0]["status"] == "error" and "bob cannot accept changes" in results[0]["error"]
        assert room.head().version == 1

    async def test_a_pasted_version_is_filed_exactly_and_replaces_the_agents(self, room, talk):
        with_agents(room)
        mine = "# Launch plan\n\n- Announce on Thursday  \n- Email the list"

        async def files_it(tools, turn):
            assert (await tools._tool_propose_version(path="plan.md", pasted_block=1))["replaces"]

        async def accepts(tools, turn):
            await tools._tool_accept()

        conversation, _, surface = await talk(room, asks_for_work, files_it, accepts)
        await conversation.hear("alice", "move it", message_id="m1", addressed=True)
        agents = await wait_for_proposal(surface, "m1")
        await conversation.hear("bob", f"here's mine:\n```\n{mine}```", thread="m1", message_id="m2")
        bobs = next(p for p in room.proposals("open") if p.author == "bob")
        await conversation.hear("alice", "go with Bob's", thread="m1", message_id="m3")

        assert room.proposal(bobs.id).status == "accepted"
        assert room.proposal(agents).reason == f"replaced by {bobs.id}"
        assert (await room.read("plan.md")).decode() == mine + "\n", "exactly as pasted"

    async def test_buttons(self, room, talk):
        with_agents(room)
        conversation, _, surface = await talk(room, asks_for_work)
        await conversation.hear("alice", "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        await conversation.press("carol", SHOW_CHANGE, proposal, "m1")
        assert "+- Announce on Wednesday" in surface.thread("m1")[-1].code
        await conversation.press("carol", ACCEPT, proposal, "m1")
        assert room.proposal(proposal).decided_by == "carol"


class TestListening:

    async def test_only_messages_for_the_room_reach_the_agent(self, room, talk):
        conversation, agent, _ = await talk(room)  # any call would fail: no scripts
        await conversation.hear("bob", "lunch anyone?", message_id="x1")
        await conversation.hear("bob", "agreed", thread="someone-elses-thread", message_id="x2")
        assert agent.briefs == []

    async def test_the_agent_sees_the_thread(self, room, talk):
        with_agents(room)
        quiet = []

        async def stays_quiet(tools, turn):
            quiet.append(turn)
            await tools._tool_stay_quiet()
            return "Not for me."

        conversation, agent, surface = await talk(room, asks_for_work, stays_quiet)
        await conversation.hear("alice", "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")
        surface.said["m1"] = [{"person": "alice", "text": "move it"}]
        before = len(surface.posts)
        await conversation.hear("bob", "@carol are you around tomorrow?", thread="m1", message_id="m2")

        assert len(surface.posts) == before, "nothing said when the agent stays quiet"
        brief = agent.briefs[-1]
        assert "in a thread you are part of" in brief
        assert f'"id": "{proposal}"' in brief and '"thread_so_far"' in brief


class TestAgentsAskingPeople:

    async def test_a_question_is_posted_in_the_work_thread_and_answered_there(self, room, talk, tmp_path):
        with_agents(room)
        hitl = HITLQueue(agent_id="room", inbox_dir=str(tmp_path / "hitl"))
        answers = []

        async def answers_it(tools, turn):
            [question] = turn.questions
            answers.append(await tools._tool_answer_question(
                question=question["id"], answer="Wednesday the 14th", decision="answered"))

        conversation, agent, surface = await talk(room, asks_for_work, answers_it, people="team", hitl=hitl)
        await conversation.hear("alice", "move it", message_id="m1", addressed=True)
        await wait_for_proposal(surface, "m1")
        workflow = next(k[3:] for k in conversation._threads if k.startswith("wf:"))
        item = hitl.assign("Which date should we announce?", "Which date?", targets=["team"],
                           context={"workflow_id": workflow, "upstream": {"draft": "Tuesday clashes"}})
        await conversation.sync()
        question = next(p for p in surface.thread("m1") if "The agents need someone" in p.text)
        assert "Which date should we announce?" in question.text and "Tuesday clashes" in question.detail

        await conversation.hear("bob", "Wednesday the 14th works", thread="m1", message_id="m2")
        assert answers[0]["status"] == "success"
        resolution = hitl.check(item)
        assert (resolution.note, resolution.resolved_by) == ("Wednesday the 14th", "bob")
        assert "questions_from_the_agents_waiting_for_people_here" in agent.briefs[-1]


class TestRemembering:

    async def test_a_restart_keeps_the_threads_and_does_not_greet_again(self, room, talk):
        with_agents(room)
        conversation, _, surface = await talk(room, asks_for_work)
        await conversation.hear("alice", "move it", message_id="m1", addressed=True)
        proposal = await wait_for_proposal(surface, "m1")

        async def accepts(tools, turn):
            assert turn.proposal == proposal
            await tools._tool_accept()

        again = RoomConversation(room, ScriptedRoomAgent(accepts), surface)
        await again.start()
        assert len([p for p in surface.posts if p.thread is None]) == 1
        await again.hear("bob", "ship it", thread="m1", message_id="m9")
        assert room.proposal(proposal).status == "accepted"

    async def test_work_started_anywhere_else_gets_its_own_thread(self, room, talk):
        conversation, _, surface = await talk(room)
        room.note("ask.started", by="dave", goal="tidy the plan", workflow_id="wf-cli")
        pushed = await room.propose({"plan.md": PLAN + "- Post on LinkedIn\n"}, author="erin")
        await conversation.sync()
        top = [p for p in surface.posts if p.thread is None]
        assert "dave asked: tidy the plan" in top[1].text
        assert top[2].proposal == pushed.id
