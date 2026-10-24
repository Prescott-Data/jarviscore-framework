"""Several people on one piece of work: one revision at a time, stale versions stay out,
and the room's agent knows what is running and how work ended."""

import asyncio
import json

import fakeredis
import pytest

from jarviscore.room import Person, Room
from jarviscore.room.agent import RoomAgent, Turn
from jarviscore.room.work import short_title
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore

PLAN = "# Launch plan\n\n- Announce on Tuesday\n"

ava, bob, dana = (Person("acme", n, n.title()) for n in ("ava", "bob", "dana"))


class FakeMesh:
    def __init__(self):
        self.cancelled = []

    def cancel_goal(self, workflow_id, *, reason=""):
        self.cancelled.append((workflow_id, reason))
        return True


@pytest.fixture
async def room(tmp_path):
    store = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    room = Room("launch", tenant="acme", blob_storage=LocalBlobStorage(str(tmp_path / "blobs")),
                redis_store=store)
    await room.ensure({"plan.md": PLAN}, by=ava)
    room.set_role(bob, "editor", by=ava)
    room.set_role(dana, "editor", by=ava)
    room.mesh = FakeMesh()
    return room


def started(room, workflow_id, by, **fields):
    room.note("ask.started", by=by.id, by_name=by.display, workflow_id=workflow_id,
              version=room.head().version, **fields)


async def proposed(room, text, **fields):
    return await room.propose({"plan.md": text}, by=ava, author="writer", **fields)


class TestOneRevisionAtATime:

    async def test_the_same_change_asked_twice_starts_one_revision(self, room):
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"), title="Move the launch")
        started(room, "room-launch-bob", bob, goal="Redo it", revision_of=first.id)
        room.redis_store.take_lease(f"{room.key}:revising:{first.id}", "room-launch-bob", 600)
        agent = RoomAgent()

        result = agent._start_work(Turn(room, dana, "me too", message_id="m3", proposal=first.id),
                                   "Redo it as Dana says", revision_of=first.id)

        assert result["already_running"] is True and result["kept_for"] == "room-launch-bob"
        assert "as Bob asked" in result["note"] and "words are kept" in result["note"]
        assert agent._work == {}, "no second workflow"
        assert RoomAgent.queued_updates(room) == [{
            "work": "room-launch-bob", "by": "dana", "by_name": "Dana", "message": "me too",
            "change": "", "id": result_id(room), "revising": first.id}]

    async def test_two_requests_at_once_start_one_revision_before_either_is_recorded(self, room):
        asks = recording(room)
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        agent = RoomAgent()

        one = agent._start_work(Turn(room, bob, "Thursday", message_id="m1"), "Thursday", revision_of=first.id)
        two = agent._start_work(Turn(room, dana, "Friday", message_id="m2"), "Friday", revision_of=first.id)
        await settle(agent)

        assert "started" in one and two["kept_for"] == one["started"]
        bobs, danas = asks
        assert bobs["by"] == "bob" and "follows" not in bobs
        assert danas["follows"] == one["started"], "Dana's is taken up after Bob's, not beside it"

    async def test_a_message_handled_again_does_not_queue_its_own_work(self, room):
        recording(room)
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        agent = RoomAgent()
        result = agent._start_work(Turn(room, bob, "Thursday", message_id="m1"), "Thursday",
                                   revision_of=first.id)
        await settle(agent)
        room.redis_store.take_lease(f"{room.key}:revising:{first.id}", result["started"], 600)

        again = RoomAgent()._start_work(Turn(room, bob, "Thursday", message_id="m1"), "Thursday",
                                        revision_of=first.id)

        assert again["started"] == result["started"] and "already started" in again["note"]
        assert RoomAgent.queued_updates(room) == []

    async def test_accepting_one_revision_closes_the_others_and_stops_their_work(self, room):
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        bobs = await proposed(room, PLAN.replace("Tuesday", "Thursday"), revision_of=first.id)
        danas = await proposed(room, PLAN.replace("Tuesday", "Friday"), revision_of=first.id)
        started(room, "room-launch-third", dana, goal="Another go", revision_of=first.id)
        started(room, "room-launch-other", dana, goal="Unrelated work")

        await room.accept(bobs.id, by=ava)

        assert room.proposal(first.id).reason == f"replaced by {bobs.id}"
        assert room.proposal(danas.id).status == "rejected"
        assert room.proposal(danas.id).reason == f"superseded by {bobs.id}"
        assert [w for w, _ in room.mesh.cancelled] == ["room-launch-third"], "unrelated work goes on"

    async def test_accepting_a_revision_of_a_revision_closes_the_whole_line(self, room):
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        second = await proposed(room, PLAN.replace("Tuesday", "Thursday"), revision_of=first.id)
        third = await proposed(room, PLAN.replace("Tuesday", "Friday"), revision_of=second.id)
        aside = await proposed(room, PLAN.replace("Tuesday", "Monday"), revision_of=first.id)

        await room.accept(third.id, by=ava)

        assert room.proposal(first.id).reason == f"replaced by {third.id}"
        assert room.proposal(second.id).reason == f"replaced by {third.id}"
        assert room.proposal(aside.id).reason == f"superseded by {third.id}"
        assert room.proposals("open") == []

    async def test_a_version_built_on_a_losing_branch_cannot_land(self, room):
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        winner = await proposed(room, PLAN.replace("Tuesday", "Thursday"), revision_of=first.id)
        loser = await proposed(room, PLAN.replace("Tuesday", "Friday"), revision_of=first.id)
        on_loser = await proposed(room, PLAN.replace("Tuesday", "Monday"), revision_of=loser.id)
        started(room, "room-launch-on-loser", dana, goal="Again", revision_of=on_loser.id)

        await room.accept(winner.id, by=ava)

        assert room.proposal(on_loser.id).reason == f"superseded by {winner.id}"
        assert "room-launch-on-loser" in [w for w, _ in room.mesh.cancelled]
        late = await proposed(room, PLAN.replace("Tuesday", "Sunday"), revision_of=on_loser.id)
        with pytest.raises(ValueError, match=f"{winner.id} already replaced"):
            await room.accept(late.id, by=ava)

    async def test_a_turned_down_proposal_remembers_the_revision_that_replaced_it(self, room):
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        await room.reject(first.id, by=bob, reason="Thursday, please")
        taken = await proposed(room, PLAN.replace("Tuesday", "Thursday"), revision_of=first.id)
        await room.accept(taken.id, by=bob)
        late = await proposed(room, PLAN.replace("Tuesday", "Friday"), revision_of=first.id)

        assert room.proposal(first.id).reason == "Thursday, please", "the reviewer's words are kept"
        assert room.overtaken_by(late.id) == taken.id
        with pytest.raises(ValueError, match="already replaced"):
            await room.accept(late.id, by=dana)

    async def test_two_people_accepting_competing_versions_at_once_land_one(self, room):
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        bobs = await proposed(room, PLAN.replace("Tuesday", "Thursday"), revision_of=first.id)
        danas = await room.propose({"notes.md": "Different file, no conflict\n"}, by=dana,
                                   revision_of=first.id)

        results = await asyncio.gather(room.accept(bobs.id, by=bob), room.accept(danas.id, by=dana),
                                       return_exceptions=True)

        assert sum(not isinstance(r, Exception) for r in results) == 1
        assert room.head().version == 2
        assert len(room.proposals("accepted")) == 1

    async def test_a_revision_of_a_proposal_already_replaced_cannot_be_accepted(self, room):
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        taken = await proposed(room, PLAN.replace("Tuesday", "Thursday"), revision_of=first.id)
        await room.accept(taken.id, by=ava)
        late = await proposed(room, PLAN.replace("Tuesday", "Friday"), revision_of=first.id)

        with pytest.raises(ValueError, match=f"that {taken.id} already replaced"):
            await room.accept(late.id, by=dana)
        assert room.head().version == 2

    async def test_a_revision_after_a_rejection_is_still_accepted(self, room):
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"))
        await room.reject(first.id, by=bob, reason="Thursday")
        again = await proposed(room, PLAN.replace("Tuesday", "Thursday"), revision_of=first.id)

        await room.accept(again.id, by=bob)
        assert room.head().version == 2


def result_id(room):
    return next(e["queued"] for e in room.events() if e.get("type") == "ask.queued")


def recording(room):
    """Stand-in for room.ask: records the work and puts it on the room's record."""
    asks = []

    async def ask(goal, *, asked_by, revision_of="", workflow_id="", title="", **options):
        asks.append({"goal": goal, "by": asked_by.id, "revision_of": revision_of,
                     "workflow_id": workflow_id, "title": title, **options})
        started(room, workflow_id, asked_by, goal=goal, revision_of=revision_of, title=title,
                **{k: options[k] for k in ("follows", "takes") if k in options})

    room.ask = ask
    return asks


async def settle(agent):
    while agent._work:
        await asyncio.gather(*list(agent._work.values()), return_exceptions=True)


class TestNothingAnyoneAddsIsLost:

    async def test_feedback_during_a_revision_is_applied_to_its_result(self, room):
        asks = recording(room)
        first = await proposed(room, PLAN.replace("Tuesday", "Wednesday"), title="Move the launch")
        started(room, "room-launch-bob", bob, goal="Move the launch", revision_of=first.id)
        agent = RoomAgent()
        agent._start_work(Turn(room, dana, "and add the email on Monday", message_id="m3"),
                          "Redo it", revision_of=first.id, change="email goes out Monday")
        bobs = await proposed(room, PLAN.replace("Tuesday", "Thursday"), revision_of=first.id)
        room.note("ask.finished", by="bob", by_name="Bob", workflow_id="room-launch-bob",
                  status="completed", summary="Thursday", proposal=bobs.id, held_for="")

        await agent._follow_up(room, "room-launch-bob")
        await settle(agent)

        [follow] = asks
        assert follow["revision_of"] == bobs.id, "it starts from the revision that just landed"
        assert follow["by"] == "dana" and follow["follows"] == "room-launch-bob"
        assert '"""\nand add the email on Monday\n"""' in follow["goal"]
        assert "As understood in the conversation: email goes out Monday" in follow["goal"]
        assert RoomAgent.queued_updates(room) == [], "taken up once"

    async def test_several_people_adding_at_once_go_to_one_follow_up(self, room):
        asks = recording(room)
        started(room, "room-launch-mail", ava, goal="Write the email sequence for the LTO")
        agent = RoomAgent()
        agent.queue_update(Turn(room, bob, "first research the ICP so the messaging leans on it",
                                message_id="m1"), "room-launch-mail")
        agent.queue_update(Turn(room, dana, "and add social media, not just email", message_id="m2"),
                           "room-launch-mail")
        room.note("ask.finished", by="ava", by_name="Ava", workflow_id="room-launch-mail",
                  status="completed", summary="Five emails", proposal="", held_for="")

        await asyncio.gather(agent._follow_up(room, "room-launch-mail"),
                             RoomAgent()._follow_up(room, "room-launch-mail"))
        await settle(agent)

        [follow] = asks
        assert "first research the ICP" in follow["goal"] and "add social media" in follow["goal"]
        assert follow["revision_of"] == "" and follow["title"].startswith("Update: Write the email")

    async def test_an_addition_to_work_that_just_ended_is_taken_up_at_once(self, room):
        asks = recording(room)
        started(room, "room-launch-mail", ava, goal="Write the email sequence")
        room.note("ask.finished", by="ava", by_name="Ava", workflow_id="room-launch-mail",
                  status="completed", summary="Done", proposal="", held_for="")
        agent = RoomAgent()

        agent.queue_update(Turn(room, bob, "also a LinkedIn post", message_id="m1"), "room-launch-mail")
        await settle(agent)

        assert len(asks) == 1 and "also a LinkedIn post" in asks[0]["goal"]

    async def test_an_addition_while_a_follow_up_runs_goes_to_that_follow_up(self, room):
        recording(room)
        started(room, "room-launch-mail", ava, goal="Write the email sequence")
        room.note("ask.finished", by="ava", by_name="Ava", workflow_id="room-launch-mail",
                  status="completed", summary="Done", proposal="", held_for="")
        started(room, "room-launch-mail-then-abc", bob, goal="Update", follows="room-launch-mail", takes=[])

        kept = RoomAgent().queue_update(Turn(room, dana, "and a tweet", message_id="m9"), "room-launch-mail")

        assert kept["kept_for"] == "room-launch-mail-then-abc"

    async def test_additions_to_stopped_work_stop_with_it(self, room):
        asks = recording(room)
        started(room, "room-launch-mail", ava, goal="Write the email sequence")
        agent = RoomAgent()
        agent.queue_update(Turn(room, bob, "add SMS", message_id="m1"), "room-launch-mail")
        room.note("ask.finished", by="ava", by_name="Ava", workflow_id="room-launch-mail",
                  status="cancelled", summary="", proposal="", held_for="")

        await agent._follow_up(room, "room-launch-mail")
        assert asks == []


class TestFollowUps:

    async def test_a_follow_up_is_told_what_the_work_before_it_reported(self, room):
        asks = recording(room)
        started(room, "room-launch-icp", ava, goal="Research the ICP")
        agent = RoomAgent()
        agent.queue_update(Turn(room, bob, "now turn that into a LinkedIn post", message_id="m1"),
                           "room-launch-icp")
        room.note("ask.finished", by="ava", by_name="Ava", workflow_id="room-launch-icp",
                  status="completed", summary="Primary ICP: holiday organisers", proposal="", held_for="")

        await agent._follow_up(room, "room-launch-icp")
        await settle(agent)

        assert "What that work reported:\nPrimary ICP: holiday organisers" in asks[0]["goal"]

    async def test_held_work_is_followed_up_as_its_owner_without_its_summary(self, room):
        asks = recording(room)
        started(room, "room-launch-inbox", bob, goal="Summarise my inbox")
        agent = RoomAgent()
        agent.queue_update(Turn(room, dana, "and list the venues", message_id="m1"), "room-launch-inbox")
        room.note("ask.finished", by="bob", by_name="Bob", workflow_id="room-launch-inbox",
                  status="completed", summary="Private: three emails", proposal="", held_for="bob")

        await agent._follow_up(room, "room-launch-inbox")
        await settle(agent)

        assert asks[0]["by"] == "bob" and "Private: three emails" not in asks[0]["goal"]

    async def test_additions_stranded_by_a_restart_are_taken_up_on_resume(self, room):
        asks = recording(room)
        started(room, "room-launch-mail", ava, goal="Write the email sequence")
        RoomAgent().queue_update(Turn(room, bob, "add SMS", message_id="m1"), "room-launch-mail")
        room.note("ask.finished", by="ava", by_name="Ava", workflow_id="room-launch-mail",
                  status="completed", summary="Done", proposal="", held_for="")

        restarted = RoomAgent()
        assert restarted.resume_work(room) == ["follow-up:room-launch-mail"]
        await settle(restarted)
        assert len(asks) == 1 and "add SMS" in asks[0]["goal"]

    async def test_a_revision_of_held_work_does_not_show_its_text(self, room):
        from jarviscore.room.work import _earlier_attempt

        held = await proposed(room, "Private notes from Bob's inbox\n")
        room.redis_store.room_transition(room.key, {"type": "test.hold", "at": 0}, proposal_id=held.id,
                                         require_status="open", proposal_fields={"held_for": "bob"})

        text = await _earlier_attempt(room, room.proposal(held.id))

        assert "plan.md" in text and "Private notes" not in text


class TestTheAgentKnowsWhereThingsStand:

    async def test_it_is_told_what_is_running_and_how_recent_work_ended(self, room):
        started(room, "room-launch-pdf", dana, goal="Make a PDF of the final draft", title="Compliance PDF")
        room.note("ask.finished", by="dana", by_name="Dana", workflow_id="room-launch-pdf",
                  status="completed", summary="Created output/review.pdf", proposal="", held_for="")
        started(room, "room-launch-mail", ava, goal="Write the email sequence for Bob")

        brief = RoomAgent._brief(Turn(room, dana, "does that mean the agents cannot do PDFs?"))
        situation = json.loads(brief.split("What is going on:\n", 1)[1])

        assert situation["work_running_now"] == [
            {"work": "room-launch-mail", "request": "Write the email sequence for Bob", "asked_by": "Ava"}]
        assert situation["recent_results"] == [{
            "request": "Compliance PDF", "status": "completed", "proposal": "none: no files changed",
            "summary": "Created output/review.pdf"}]

    async def test_held_work_is_not_in_the_results_others_see(self, room):
        started(room, "room-launch-mail", bob, goal="Summarise my inbox")
        room.note("ask.finished", by="bob", by_name="Bob", workflow_id="room-launch-mail",
                  status="completed", summary="Three emails about the venue", proposal="p-1",
                  held_for="bob")
        assert RoomAgent.recent_results(room) == []

    def test_questions_and_agreement_are_answered_not_dispatched(self):
        from jarviscore.room.agent import RoomSubAgent

        prompt = RoomSubAgent.SYSTEM_PROMPT
        assert "a request for new work: ask_agents" in prompt
        assert "question about what the agents can do" in prompt
        assert "never start the work a second time" in prompt
        assert "more for work that is still running" in prompt and "update_work" in prompt


class TestTitles:

    @pytest.mark.parametrize("goal, title", [
        ("Fix the app. Then run the tests.", "Fix the app."),
        ("Draft the launch post\n\nWith the brief's numbers", "Draft the launch post"),
        ("Ava Chen says: \"We have campaigns we need to set for our LTO on the Amex Platinum card "
         "especially during this period where people are planning out holidays.\"",
         "Ava Chen says: \"We have campaigns we need to set for our LTO on the Amex…"),
    ])
    def test_a_title_is_the_first_sentence_cut_at_a_word(self, goal, title):
        assert short_title(goal) == title
        assert len(short_title(goal)) <= 80
