"""A room in a Slack channel: asking, watching, reviewing and taking over from Slack."""

import asyncio

import pytest

from jarviscore.chat.slack import SlackClient, SlackError, escape, unescape, without_mention
from jarviscore.human.channels import WorkItem
from jarviscore.room import FileRoomLedger, Room
from jarviscore.room.slack import ACCEPT_ACTION, DIFF_ACTION, SlackPeopleChannel, SlackRoom
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.testing.slack import FakeSlack

CHANNEL = "C1"
PLAN = "# Launch plan\n\n- Announce on Tuesday\n- Email the list\n"


async def until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.02)


@pytest.fixture
async def slack():
    fake = await FakeSlack(users={"U1": "alice", "U2": "bob", "U3": "carol"}).start()
    yield fake
    await fake.stop()


def make_room(tmp_path):
    return Room("launch", blob_storage=LocalBlobStorage(str(tmp_path / "blobs")),
                ledger=FileRoomLedger(str(tmp_path / "rooms")))


def with_agents(room):
    """Stand-in for Room.for_mesh: 'agents' that tighten the plan the way a mesh run would."""
    asks = []

    async def ask(goal, *, asked_by, revision_of="", workflow_id="", **options):
        asks.append({"goal": goal, "asked_by": asked_by, "revision_of": revision_of,
                     "workflow_id": workflow_id})
        head = room.head()
        room.note("ask.started", by=asked_by, goal=goal, workflow_id=workflow_id,
                  version=head.version, revision_of=revision_of)
        room.note("step.claimed", workflow_id=workflow_id, by="writer", step="step-1")
        room.note("step.completed", workflow_id=workflow_id, by="writer", step="step-1")
        current = (await room.read("plan.md")).decode()
        proposal = await room.propose(
            {"plan.md": current.replace("Tuesday", "Wednesday")}, author="writer",
            asked_by=asked_by, title=goal, base_version=head.version,
            workflow_id=workflow_id, revision_of=revision_of)
        room.note("ask.finished", by=asked_by, workflow_id=workflow_id, status="completed",
                  summary="Moved the announcement to Wednesday.", proposal=proposal.id)

    room.mesh = object()
    room.ask = ask
    return asks


@pytest.fixture
async def served(slack, tmp_path):
    room = make_room(tmp_path)
    await room.ensure({"plan.md": PLAN}, by="alice")
    asks = with_agents(room)
    client = SlackClient("xoxb-test", "xapp-test", api_url=slack.api_url)
    bridge = SlackRoom(room, CHANNEL, client=client, poll_interval=0.05)
    task = asyncio.create_task(bridge.run())
    await slack.connected()
    await until(lambda: slack.bot_messages(CHANNEL))
    yield room, bridge, asks
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def mention(slack, text):
    return f"<@{slack.bot_user_id}> {text}"


def texts(slack, ts):
    return [m["text"] for m in slack.thread(ts) if m["user"] == slack.bot_user_id]


def proposal_messages(slack, ts):
    return [m for m in slack.thread(ts) if m.get("blocks")]


def proposal_message(slack, ts):
    return next(m for m in slack.thread(ts) if m.get("blocks"))


async def ask_and_wait(slack, room, text="move the announcement", user="U1"):
    ts = await slack.say(user, mention(slack, text), channel=CHANNEL)
    await until(lambda: room.proposals("open") and any(m.get("blocks") for m in slack.thread(ts)))
    return ts


class TestText:

    def test_escape_and_unescape_round_trip_what_people_typed(self):
        typed = "a < b & c > d"
        assert escape(typed) == "a &lt; b &amp; c &gt; d"
        assert unescape(escape(typed)) == typed

    def test_links_come_back_as_typed(self):
        assert unescape("see <https://x.io/a|x.io/a> and <https://y.io>") == "see x.io/a and https://y.io"

    def test_mentions_of_the_bot_are_removed(self):
        assert without_mention("<@UBOT> draft it", "UBOT") == "draft it"


class TestClient:

    async def test_start_learns_the_bot_and_users_are_cached(self, slack):
        client = SlackClient("xoxb-test", api_url=slack.api_url)
        await client.start()
        assert client.bot_user_id == "UBOT"
        assert (await client.user("U1"))["name"] == "alice"
        await client.user("U1")
        assert slack.calls.count("users.info") == 1
        await client.close()

    async def test_rate_limits_are_waited_out(self, slack):
        client = SlackClient("xoxb-test", api_url=slack.api_url)
        slack.rate_limit_next = 2
        ts = await client.post(CHANNEL, "hello")
        assert ts and slack.messages[-1]["text"] == "hello"
        await client.close()

    async def test_slack_errors_raise(self, slack):
        client = SlackClient("xoxb-wrong", api_url=slack.api_url)
        with pytest.raises(SlackError) as caught:
            await client.start()
        assert caught.value.error == "invalid_auth"
        await client.close()

    def test_a_bot_token_is_required(self, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            SlackClient()

    async def test_socket_mode_acks_and_reconnects_when_slack_asks(self, slack):
        client = SlackClient("xoxb-test", "xapp-test", api_url=slack.api_url)
        received = []

        async def listen():
            async for envelope in client.events():
                received.append(envelope)

        task = asyncio.create_task(listen())
        await slack.connected()
        await slack.say("U1", "first", channel=CHANNEL)
        await until(lambda: len(received) == 1)
        await slack.disconnect()
        await until(lambda: slack.calls.count("apps.connections.open") == 2)
        await slack.say("U1", "second", channel=CHANNEL)
        await until(lambda: len(received) == 2)
        assert [e["payload"]["event"]["text"] for e in received] == ["first", "second"]
        await until(lambda: {e["envelope_id"] for e in received} <= slack.acked)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await client.close()


class TestConnecting:

    async def test_says_hello_once_and_picks_up_where_it_left_off(self, slack, tmp_path):
        room = make_room(tmp_path)
        await room.ensure({"plan.md": PLAN}, by="alice")
        client = SlackClient("xoxb-test", api_url=slack.api_url)
        first = SlackRoom(room, CHANNEL, client=client)
        await first.start()
        hello = slack.bot_messages(CHANNEL)
        assert len(hello) == 1 and "launch" in hello[0]["text"]

        room.note("ask.started", by="dave", goal="from the CLI", workflow_id="wf-1")
        again = SlackRoom(room, CHANNEL, client=client)
        await again.start()
        await again.sync()
        posted = [m["text"] for m in slack.bot_messages(CHANNEL)]
        assert len(posted) == 2 and "dave asked: from the CLI" in posted[1]
        await client.close()


class TestAskingFromSlack:

    async def test_a_mention_becomes_a_thread_with_the_work_and_its_proposal(self, slack, served):
        room, bridge, asks = served
        ts = await ask_and_wait(slack, room, "move the <launch> & announcement")

        assert asks[0]["goal"] == "move the <launch> & announcement"
        assert asks[0]["asked_by"] == "alice"
        replies = texts(slack, ts)
        assert replies[0].startswith("On it, alice")
        assert any("writer took step-1" in t for t in replies)
        proposal = proposal_message(slack, ts)
        assert "proposed by writer for alice" in proposal["text"]
        assert "&lt;launch&gt; &amp;" in proposal["text"]
        diff = proposal["blocks"][1]["text"]["text"]
        assert "-- Announce on Tuesday" in diff and "+- Announce on Wednesday" in diff
        actions = proposal["blocks"][2]["elements"]
        assert [a["action_id"] for a in actions] == [ACCEPT_ACTION, DIFF_ACTION]
        await until(lambda: any("Moved the announcement" in t for t in texts(slack, ts)))
        # ask.started is not repeated: the person's own message is the thread.
        assert not any("alice asked" in t for t in texts(slack, ts))

    async def test_accept_in_the_thread_merges_as_the_person_who_said_it(self, slack, served):
        room, _, _ = served
        ts = await ask_and_wait(slack, room)
        await slack.say("U2", "accept", channel=CHANNEL, thread_ts=ts)
        await until(lambda: room.head().version == 2)
        assert room.head().updated_by == "bob"
        assert "Wednesday" in (await room.read("plan.md")).decode()
        await until(lambda: any(t.startswith("✓ bob accepted") for t in texts(slack, ts)))

    async def test_the_accept_button_works_too(self, slack, served):
        room, _, _ = served
        ts = await ask_and_wait(slack, room)
        message = proposal_message(slack, ts)
        proposal = room.proposals("open")[0].id
        await slack.click("U3", ACCEPT_ACTION, proposal, message_ts=message["ts"])
        await until(lambda: room.head().version == 2)
        assert room.proposal(proposal).decided_by == "carol"

    async def test_reject_needs_a_reason(self, slack, served):
        room, _, _ = served
        ts = await ask_and_wait(slack, room)
        await slack.say("U2", "reject", channel=CHANNEL, thread_ts=ts)
        await until(lambda: any("Say why" in t for t in texts(slack, ts)))
        assert room.proposals("open")
        await slack.say("U2", "reject Tuesday is fixed", channel=CHANNEL, thread_ts=ts)
        await until(lambda: not room.proposals("open"))
        rejected = room.proposals("rejected")[0]
        assert (rejected.decided_by, rejected.reason) == ("bob", "Tuesday is fixed")
        await until(lambda: any("✗ bob rejected" in t for t in texts(slack, ts)))

    async def test_redo_turns_it_down_and_has_it_done_again_in_the_same_thread(self, slack, served):
        room, _, asks = served
        ts = await ask_and_wait(slack, room, "move the announcement")
        first = room.proposals("open")[0].id
        await slack.say("U2", "redo keep the email on Monday", channel=CHANNEL, thread_ts=ts)
        await until(lambda: len(asks) == 2 and room.proposals("open"))
        assert asks[1]["revision_of"] == first
        assert asks[1]["asked_by"] == "bob"
        assert room.proposal(first).reason == "keep the email on Monday"
        second = room.proposals("open")[0].id
        await until(lambda: sum(1 for m in slack.thread(ts) if m.get("blocks")) == 2)
        # The newest proposal is the one the thread now talks about.
        await slack.say("U1", "accept", channel=CHANNEL, thread_ts=ts)
        await until(lambda: room.proposal(second).status == "accepted")

    async def test_a_conflicting_accept_says_what_changed_and_redo_starts_over(self, slack, served):
        room, _, asks = served
        ts = await ask_and_wait(slack, room)
        proposal = room.proposals("open")[0].id
        other = await room.propose({"plan.md": PLAN.replace("Tuesday", "Friday")}, author="dave")
        await room.accept(other.id, by="dave")
        await slack.say("U2", f"accept {proposal}", channel=CHANNEL, thread_ts=ts)
        await until(lambda: any("Not accepted: plan.md changed" in t for t in texts(slack, ts)))
        assert room.proposal(proposal).status == "conflicted"

        await slack.say("U2", "redo", channel=CHANNEL, thread_ts=ts)
        await until(lambda: len(asks) == 2)
        assert asks[1]["revision_of"] == proposal


class TestWhoMayDoWhat:

    async def test_roles_hold_in_slack(self, slack, served):
        room, _, asks = served
        room.set_role("bob", "viewer", by="alice")
        ts = await ask_and_wait(slack, room)
        await slack.say("U2", "accept", channel=CHANNEL, thread_ts=ts)
        await until(lambda: any("bob cannot accept changes" in t for t in texts(slack, ts)))
        assert room.head().version == 1

        top = await slack.say("U3", mention(slack, "rewrite everything"), channel=CHANNEL)
        await until(lambda: any("carol cannot ask for work" in t for t in texts(slack, top)))
        assert len(asks) == 1

    async def test_slack_users_can_be_mapped_to_room_members(self, slack, tmp_path):
        room = make_room(tmp_path)
        bridge = SlackRoom(room, CHANNEL, client=SlackClient("xoxb-test", api_url=slack.api_url),
                           people={"U1": "alice@acme.com"})
        assert await bridge.person("U1") == "alice@acme.com"
        assert await bridge.person("U2") == "bob"
        await bridge.client.close()


class TestTakingOver:

    async def test_edit_with_a_code_block_proposes_your_own_version(self, slack, served):
        room, _, asks = served
        ts = await ask_and_wait(slack, room)
        mine = "# Launch plan\n\n- Announce on Thursday\n- Email the list"
        await slack.say("U2", f"edit plan.md\n```{mine}```", channel=CHANNEL, thread_ts=ts)
        await until(lambda: any(p.author == "bob" for p in room.proposals("open")))
        bobs = next(p for p in room.proposals("open") if p.author == "bob")
        await until(lambda: len(proposal_messages(slack, ts)) == 2)
        assert "Thursday" in "".join(c.unified() for c in await room.diff(bobs.id))
        assert "proposed by bob:" in proposal_messages(slack, ts)[-1]["text"]
        agents = next(p for p in room.proposals("open") if p.author == "writer")
        await slack.say("U1", "accept", channel=CHANNEL, thread_ts=ts)
        await until(lambda: room.proposal(bobs.id).status == "accepted")
        # Bob's version replaced the agents' draft, so that one is closed.
        assert room.proposal(agents.id).reason == f"replaced by {bobs.id}"
        await until(lambda: any(f"rejected {agents.id}: replaced by" in t for t in texts(slack, ts)))
        # A trailing newline the file had is kept.
        assert (await room.read("plan.md")).decode() == mine + "\n"
        assert len(asks) == 1

    async def test_a_request_that_starts_with_edit_is_still_a_request(self, slack, served):
        room, _, asks = served
        await slack.say("U1", mention(slack, "edit the plan to add a FAQ"), channel=CHANNEL)
        await until(lambda: asks)
        assert asks[0]["goal"] == "edit the plan to add a FAQ"

    async def test_show_status_and_help(self, slack, served):
        room, _, _ = served
        top = await slack.say("U1", mention(slack, "show plan.md"), channel=CHANNEL)
        await until(lambda: any("Announce on Tuesday" in t for t in texts(slack, top)))
        top = await slack.say("U1", mention(slack, "show"), channel=CHANNEL)
        await until(lambda: any("Files: `plan.md`" in t for t in texts(slack, top)))
        top = await slack.say("U1", mention(slack, "status"), channel=CHANNEL)
        await until(lambda: any("v1, 1 files" in t for t in texts(slack, top)))
        top = await slack.say("U1", mention(slack, ""), channel=CHANNEL)
        await until(lambda: any("Mention me with what you need" in t for t in texts(slack, top)))

    async def test_full_diff_on_request(self, slack, served):
        room, _, _ = served
        ts = await ask_and_wait(slack, room)
        await slack.say("U3", "diff", channel=CHANNEL, thread_ts=ts)
        await until(lambda: sum("+- Announce on Wednesday" in t for t in texts(slack, ts)) == 1)


class TestListening:

    async def test_chatter_and_the_bots_own_messages_are_left_alone(self, slack, served):
        room, _, asks = served
        ts = await ask_and_wait(slack, room)
        before = len(slack.bot_messages())
        await slack.say("U2", "lunch anyone?", channel=CHANNEL)
        await slack.say("U2", "nice, looks right to me", channel=CHANNEL, thread_ts=ts)
        await slack.say("U2", mention(slack, "help"), channel="C-other")
        await asyncio.sleep(0.3)
        assert len(slack.bot_messages()) == before
        assert len(asks) == 1

    async def test_a_mention_is_acted_on_once(self, slack, served):
        room, _, asks = served
        await ask_and_wait(slack, room)
        await asyncio.sleep(0.2)
        assert len(asks) == 1


class TestWorkFromElsewhere:

    async def test_work_from_the_cli_shows_up_with_its_own_thread(self, slack, served):
        room, _, _ = served
        room.note("ask.started", by="dave", goal="tidy the plan", workflow_id="wf-cli")
        room.note("step.completed", workflow_id="wf-cli", by="writer", step="step-1")
        await until(lambda: any("dave asked: tidy the plan" in m["text"] for m in slack.bot_messages()))
        root = next(m for m in slack.bot_messages() if "dave asked" in m["text"])
        await until(lambda: any("writer finished step-1" in t for t in texts(slack, root["ts"])))

        pushed = await room.propose({"plan.md": PLAN + "- Post on LinkedIn\n"}, author="erin",
                                    title="add LinkedIn")
        await until(lambda: any(pushed.id in m["text"] and not m["thread_ts"]
                                for m in slack.bot_messages()))
        thread = next(m["ts"] for m in slack.bot_messages() if pushed.id in m["text"])
        await room.accept(pushed.id, by="erin")
        await until(lambda: any(t.startswith("✓ erin accepted") for t in texts(slack, thread)))


class TestAgentsAskingPeople:

    async def test_a_question_lands_in_the_work_thread_and_anyone_there_answers(self, slack, tmp_path):
        room = make_room(tmp_path)
        await room.ensure({"plan.md": PLAN}, by="alice")
        people = SlackPeopleChannel()
        bridge = SlackRoom(room, CHANNEL, client=SlackClient("xoxb-test", "xapp-test", api_url=slack.api_url),
                           people_channel=people, poll_interval=0.05)
        task = asyncio.create_task(bridge.run())
        await slack.connected()
        root = await slack.say("U1", "kick off", channel=CHANNEL)
        bridge._threads["wf:wf-9"] = root

        item = WorkItem(id="t1", task="Which date should we announce?", workflow_id="wf-9",
                        upstream={"step-1": "Tuesday clashes with a holiday"})
        answer = asyncio.create_task(people.ask(item))
        await until(lambda: any("A person is needed" in t for t in texts(slack, root)))
        question = next(t for t in texts(slack, root) if "A person is needed" in t)
        assert "Tuesday clashes" in question
        await slack.say("U2", "Wednesday the 14th", channel=CHANNEL, thread_ts=root)
        result = await asyncio.wait_for(answer, 5)
        assert (result.decision, result.response, result.by) == ("answered", "Wednesday the 14th", "bob")

        second = asyncio.create_task(people.ask(WorkItem(id="t2", task="Sign off?", workflow_id="wf-9")))
        await until(lambda: any("Sign off?" in t for t in texts(slack, root)))
        await slack.say("U3", "reject budget is not approved", channel=CHANNEL, thread_ts=root)
        result = await asyncio.wait_for(second, 5)
        assert (result.decision, result.response, result.by) == ("rejected", "budget is not approved", "carol")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class TestThroughTheMesh:
    """Slack → a real mesh's agents → a person in the thread → a proposal → accepted from Slack."""

    async def test_the_whole_loop(self, slack, tmp_path, monkeypatch):
        from pathlib import Path

        import fakeredis

        from jarviscore import Mesh
        from jarviscore.human import HumanAgent
        from jarviscore.orchestration.envelopes import DependencyAuthorization
        from jarviscore.profiles import CustomAgent
        from jarviscore.storage.redis_store import RedisContextStore

        class FileSandbox:
            def __init__(self, workspace=None):
                self.workspace = workspace

            def for_workspace(self, workspace_dir, **_options):
                return FileSandbox(workspace_dir)

        class Planner(CustomAgent):
            role = "planner"
            capabilities = ["planning"]

            def __init__(self, agent_id=None):
                super().__init__(agent_id)
                self.sandbox = FileSandbox()

            async def authorize_dependencies(self, task, artifacts, interpretations):
                return DependencyAuthorization("allow", "test")

            async def execute_task(self, task):
                plan = Path(task["context"]["workspace_binding"]["path"]) / "plan.md"
                plan.write_text(plan.read_text().replace("Tuesday", "Wednesday"))
                return {"status": "success", "output": "Moved the announcement to Wednesday"}

        redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
        monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
        monkeypatch.setattr(Mesh, "_init_blob_storage",
                            lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
        monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
        monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
        monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)

        people = SlackPeopleChannel()
        mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02})
        mesh.add(Planner)
        mesh.add(HumanAgent("team", ["signoff"], channel=people))
        await mesh.start()
        try:
            room = Room.for_mesh(mesh, "launch")
            await room.ensure({"plan.md": PLAN}, by="alice")
            goal = "Move the announcement"
            template = {
                "obligations": [{"id": "o1", "description": goal, "source_quote": goal}],
                "steps": [
                    {"id": "draft", "capability": "planning", "effect": "propose", "systems": [],
                     "task": "Move the announcement to Wednesday", "success_criterion": "moved",
                     "expected_findings": ["date"], "depends_on": [], "covers": []},
                    {"id": "signoff", "capability": "signoff", "effect": "propose", "systems": [],
                     "task": "Is Wednesday fine with marketing?", "success_criterion": "signed off",
                     "expected_findings": ["decision"], "depends_on": ["draft"], "covers": ["o1"]},
                ],
            }
            bridge = SlackRoom(room, CHANNEL, people_channel=people, poll_interval=0.05,
                               client=SlackClient("xoxb-test", "xapp-test", api_url=slack.api_url),
                               ask_options={"timeout": 20, "plan_template": template})
            served = asyncio.create_task(bridge.run())
            await slack.connected()

            ts = await slack.say("U1", mention(slack, goal), channel=CHANNEL)
            await until(lambda: any("A person is needed for signoff" in t for t in texts(slack, ts)), 15)
            question = next(t for t in texts(slack, ts) if "A person is needed" in t)
            assert "Is Wednesday fine with marketing?" in question
            assert "Moved the announcement to Wednesday" in question, "the person sees the agent's work"

            await slack.say("U2", "approve marketing is fine with it", channel=CHANNEL, thread_ts=ts)
            await until(lambda: room.proposals("open"), 15)
            proposal = room.proposals("open")[0]
            assert proposal.asked_by == "alice"
            await until(lambda: any(m.get("blocks") for m in slack.thread(ts)))
            replies = texts(slack, ts)
            assert any("planner took draft" in t for t in replies)
            assert any("team" in t and "signoff" in t for t in replies)

            await slack.say("U3", "accept", channel=CHANNEL, thread_ts=ts)
            await until(lambda: room.head().version == 2)
            assert "Wednesday" in (await room.read("plan.md")).decode()
            assert room.head().updated_by == "carol"
            served.cancel()
            await asyncio.gather(served, return_exceptions=True)
        finally:
            await mesh.stop()
