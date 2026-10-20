"""Rooms in Slack, with Slack reached only through Nexus."""

import asyncio
import json

import fakeredis
import pytest

from jarviscore.execution.workspace import SandboxBinding
from jarviscore.nexus import store as vault
from jarviscore.room import Account, CONFIRM, Identities, Person, Room
from jarviscore.room.slack import SlackApi, SlackApp, SlackError, escape, unescape
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore
from jarviscore.testing.rooms import ScriptedRoomAgent
from jarviscore.testing.slack import FakeSlack

CHANNEL = "C1"
PLAN = "# Launch plan\n\n- Announce on Tuesday\n- Email the list\n"
ACCEPT_ACTION, CHANGE_ACTION = "room.accept", "room.show_change"


async def until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.02)


@pytest.fixture
async def slack():
    fake = await FakeSlack(
        users={"U1": "alice", "U2": "bob", "U3": "carol",
               "U4": {"name": "gus", "guest": True}, "U5": {"name": "olga", "team": "T-OTHER"}},
        redeliver_after=0.3,
    ).start()
    fake.add_channel(CHANNEL, private=True, members=["U1", "U2", "U3"])
    yield fake
    await fake.stop()


@pytest.fixture
def nexus(tmp_path, monkeypatch, slack):
    """A Nexus vault holding the workspace's two Slack credentials, in a temp directory."""
    monkeypatch.setattr(vault, "_STORE_DIR", tmp_path / "jarviscore")
    monkeypatch.setattr(vault, "_STORE_FILE", tmp_path / "jarviscore" / "nexus.enc")
    monkeypatch.setattr(vault, "_SALT_FILE", tmp_path / "jarviscore" / ".salt")
    monkeypatch.setenv("NEXUS_SECRET", "test-secret")
    store = vault.NexusLocalStore(tmp_path / "jarviscore" / "nexus.enc")
    monkeypatch.setattr(vault, "_default_store", store)
    # The stand-in Slack is not slack.com, so the connections name its host.
    base = f"http://127.0.0.1:{slack.port}"
    for provider, token in (("slack", slack.bot_token), ("slack_app", slack.app_token)):
        store.register(provider, slack_credential(token, base))
    return store


def slack_credential(token, base_url=None):
    """What `jarviscore nexus register slack --auth-type api_key --header-name Authorization
    --value-prefix "Bearer " --api-key ...` stores."""
    entry = {"auth_type": "api_key", "api_key": token,
             "auth_config": {"header_name": "Authorization", "value_prefix": "Bearer "}}
    return {**entry, "base_url": base_url} if base_url else entry


def slack_person(room, user, name):
    """The person a Slack user is, as SlackApp resolves them."""
    return Identities(room.redis_store).person_for(Account("acme", "slack:T1", user, name))


@pytest.fixture
async def room(tmp_path):
    """Alice's private room; Bob and Carol edit it. Everyone in the channel is in the room."""
    store = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    room = Room("launch", tenant="acme", blob_storage=LocalBlobStorage(str(tmp_path / "blobs")),
                redis_store=store)
    alice = slack_person(room, "U1", "alice")
    await room.ensure({"plan.md": PLAN}, by=alice)
    room.set_role(slack_person(room, "U2", "bob"), "editor", by=alice)
    room.set_role(slack_person(room, "U3", "carol"), "editor", by=alice)
    return room


def with_agents(room, *, held=False):
    async def ask(goal, *, asked_by, revision_of="", workflow_id="", **options):
        head = room.head()
        who = {"by": asked_by.id, "by_name": asked_by.display}
        room.note("ask.started", **who, goal=goal, workflow_id=workflow_id, version=head.version)
        changed = PLAN.replace("Tuesday", "Wednesday <b> & co")
        if held:
            snapshot = await room.snapshot()
            async with SandboxBinding(room.store, snapshot) as binding:
                (binding.workspace / "plan.md").write_text(changed)
                delta = await binding.export_delta(f"workflows/{workflow_id}/workspace_deltas/s")
            proposal = await room.propose_deltas(
                [delta], base_version=head.version, author="writer", asked_by=asked_by, title=goal,
                workflow_id=workflow_id, held_for=asked_by.id)
        else:
            proposal = await room.propose({"plan.md": changed}, by=asked_by, author="writer",
                                          title=goal, base_version=head.version, workflow_id=workflow_id)
        room.note("ask.finished", **who, workflow_id=workflow_id, status="completed",
                  summary="Moved it, from Bob's inbox." if held else "Moved it.",
                  proposal=proposal.id, held_for=asked_by.id if held else "")

    room.mesh = object()
    room.ask = ask


async def asks_for_work(tools, turn):
    await tools._tool_ask_agents(goal="Move the announcement")
    return "On it, <working> & will post here."


@pytest.fixture
async def served(slack, nexus, room):
    """SlackApps on their own Nexus-backed APIs, running as they would in production."""
    started = []

    async def serve(*scripts, rooms=None, greeted=True, **options):
        agent = ScriptedRoomAgent(*scripts)
        api = await SlackApi.through_nexus(None, api_url=slack.api_url)
        app = SlackApp(agent, tenant="acme", api=api, poll_interval=0.02, **options)
        for each, channel in (rooms or [(room, CHANNEL)]):
            app.connect(each, channel)
        before = len(slack._sockets)
        started.append(asyncio.create_task(app.run()))
        await slack.connected(count=before + 1)
        if greeted:
            await until(lambda: slack.bot_messages(CHANNEL))
        return app, agent

    yield serve
    for task in started:
        task.cancel()
    await asyncio.gather(*started, return_exceptions=True)


def mention(slack, text):
    return f"<@{slack.bot_user_id}> {text}"


def texts(slack, ts):
    return [m["text"] for m in slack.thread(ts) if m["user"] == slack.bot_user_id]


def proposal_message(slack, ts):
    return next(m for m in slack.thread(ts) if m.get("blocks"))


def value(room, target):
    return json.dumps({"r": room.key, "t": target})


class TestText:

    def test_escape_and_unescape_round_trip_what_people_typed(self):
        typed = "a < b & c > d"
        assert unescape(escape(typed)) == typed

    def test_links_come_back_as_typed(self):
        assert unescape("see <https://x.io/a|x.io/a> and <https://y.io>") == "see x.io/a and https://y.io"


class TestThroughNexus:

    async def test_calls_carry_the_workspaces_bot_token_and_no_token_is_given_to_jarviscore(self, slack, nexus):
        api = await SlackApi.through_nexus(None, api_url=slack.api_url)
        assert not any("xoxb" in repr(v) or "xapp" in repr(v) for v in vars(api).values())
        await api.start()
        assert (api.bot_user_id, api.team_id) == ("UBOT", "T1"), "the fake only answers the right bot token"
        assert (await api.user("U1"))["name"] == "alice"

    async def test_slack_refusals_raise(self, slack, nexus):
        nexus.register("slack", slack_credential("xoxb-wrong", f"http://127.0.0.1:{slack.port}"))
        api = await SlackApi.through_nexus(None, api_url=slack.api_url)
        with pytest.raises(SlackError) as caught:
            await api.start()
        assert caught.value.error == "invalid_auth"

    async def test_rate_limits_are_waited_out(self, slack, nexus):
        api = await SlackApi.through_nexus(None, api_url=slack.api_url)
        slack.rate_limit_next = 2
        assert await api.post(CHANNEL, "hello")

    async def test_a_credential_is_never_sent_to_a_host_it_does_not_belong_to(self, slack, nexus):
        nexus.register("slack", slack_credential(slack.bot_token))
        api = await SlackApi.through_nexus(None, api_url=slack.api_url)
        with pytest.raises(Exception, match="may not be sent"):
            await api.start()

    async def test_socket_mode_opens_with_the_app_token_and_reconnects_when_asked(self, slack, nexus):
        api = await SlackApi.through_nexus(None, api_url=slack.api_url)
        received = []

        async def listen():
            async for envelope, ack in api.events():
                received.append(envelope)
                await ack()

        task = asyncio.create_task(listen())
        await slack.connected()
        await slack.say("U1", "first", channel=CHANNEL)
        await until(lambda: len(received) == 1)
        await slack.disconnect()
        await until(lambda: slack.calls.count("apps.connections.open") == 2)
        await slack.say("U1", "second", channel=CHANNEL)
        await until(lambda: len(received) == 2)
        await until(lambda: {e["envelope_id"] for e in received} <= slack.acked)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class TestInTheChannel:

    async def test_a_mention_becomes_a_thread_with_the_work_and_its_proposal(self, slack, served, room):
        with_agents(room)
        await served(asks_for_work)
        ts = await slack.say("U1", mention(slack, "can we <launch> wednesday?"), channel=CHANNEL)
        await until(lambda: any(m.get("blocks") for m in slack.thread(ts)))

        assert texts(slack, ts)[0] == "On it, &lt;working&gt; &amp; will post here."
        blocks = proposal_message(slack, ts)["blocks"]
        assert "+- Announce on Wednesday &lt;b&gt; &amp; co" in blocks[1]["text"]["text"]
        buttons = blocks[2]["elements"]
        assert [b["action_id"] for b in buttons] == [ACCEPT_ACTION, CHANGE_ACTION]
        assert json.loads(buttons[0]["value"])["r"] == "acme/launch"
        await until(lambda: any("\n>Moved it." in t for t in texts(slack, ts)))
        assert room.proposals("open")[0].asked_by == "slack:T1.U1"

    async def test_a_decision_is_confirmed_by_the_person_who_made_it(self, slack, served, room):
        with_agents(room)
        heard = []

        async def accepts(tools, turn):
            heard.append(turn)
            await tools._tool_prepare_decision(action="accept")
            return "Tap Confirm and it's in."

        await served(asks_for_work, accepts)
        ts = await slack.say("U1", mention(slack, "move it"), channel=CHANNEL)
        await until(lambda: any(m.get("blocks") for m in slack.thread(ts)))
        await slack.say("U2", "looks great, ship it", channel=CHANNEL, thread_ts=ts)
        await until(lambda: slack.seen_only_by("U2"))

        assert heard[0].person == Person("acme", "slack:T1.U2", "bob")
        assert heard[0].history[0]["text"] == "move it"
        assert room.head().version == 1, "nothing happens from the message alone"
        [ask] = slack.seen_only_by("U2")
        confirm = next(b for b in ask["blocks"][1]["elements"] if b["action_id"] == "room.confirm")

        await slack.click("U3", "room.confirm", confirm["value"], message_ts=ask["ts"])
        await asyncio.sleep(0.2)
        assert room.head().version == 1, "only Bob can confirm Bob's decision"
        await slack.click("U2", "room.confirm", confirm["value"], message_ts=ask["ts"])
        await until(lambda: room.head().version == 2)
        assert room.head().updated_by == "slack:T1.U2"
        await until(lambda: any(t.startswith("✓ bob accepted") for t in texts(slack, ts)))

    async def test_the_buttons_act_for_whoever_presses_them(self, slack, served, room):
        with_agents(room)
        await served(asks_for_work)
        ts = await slack.say("U1", mention(slack, "move it"), channel=CHANNEL)
        await until(lambda: any(m.get("blocks") for m in slack.thread(ts)))
        message = proposal_message(slack, ts)
        proposal = room.proposals("open")[0].id
        await slack.click("U3", CHANGE_ACTION, value(room, proposal), message_ts=message["ts"])
        await until(lambda: any("The full change in" in t for t in texts(slack, ts)))
        await slack.click("U3", ACCEPT_ACTION, value(room, proposal), message_ts=message["ts"])
        await until(lambda: room.head().version == 2)
        assert room.head().updated_by == "slack:T1.U3"

    async def test_only_messages_for_the_room_reach_the_agent_and_a_mention_once(self, slack, served):
        heard = []

        async def listens(tools, turn):
            heard.append(turn.message)

        await served(listens)
        await slack.say("U2", "lunch anyone?", channel=CHANNEL)
        await slack.say("U2", mention(slack, "hi"), channel="C-other")
        await slack.say("U2", mention(slack, "status please"), channel=CHANNEL)
        await until(lambda: heard)
        await asyncio.sleep(0.5)
        assert heard == ["status please"], "once, though Slack sends a mention twice"

    async def test_the_channel_is_greeted_once(self, slack, nexus, room):
        for _ in range(2):
            api = await SlackApi.through_nexus(None, api_url=slack.api_url)
            app = SlackApp(ScriptedRoomAgent(), tenant="acme", api=api)
            app.connect(room, CHANNEL)
            await app.start()
        assert len(slack.bot_messages(CHANNEL)) == 1
        assert "The launch room is connected here" in slack.bot_messages(CHANNEL)[0]["text"]

    async def test_one_app_serves_each_room_in_its_own_channel(self, slack, served, room):
        other = Room("hiring", tenant="acme", blob_storage=room.store.blob_storage, redis_store=room.redis_store)
        await other.ensure({"roles.md": "# Roles\n"}, by=slack_person(room, "U1", "alice"))
        slack.add_channel("C2", private=True, members=["U1"])
        heard = []

        async def listens(tools, turn):
            heard.append((turn.room.id, turn.message))

        await served(listens, listens, rooms=[(room, CHANNEL), (other, "C2")])
        await until(lambda: slack.bot_messages("C2"))
        await slack.say("U1", mention(slack, "launch?"), channel=CHANNEL)
        await slack.say("U1", mention(slack, "hiring?"), channel="C2")
        await until(lambda: len(heard) == 2)
        assert sorted(heard) == [("hiring", "hiring?"), ("launch", "launch?")]

    async def test_your_own_people_can_stand_for_slack_users(self, slack, served, room):
        heard = []
        ours = Person("acme", "alice@acme.com", "Alice")
        room.set_role(ours, "editor", by=slack_person(room, "U1", "alice"))

        async def listens(tools, turn):
            heard.append(turn.person)

        # Your directory knows Alice; everyone else in the channel is who Slack says they are.
        await served(listens, identify=lambda user: ours if user["id"] == "U1"
                     else slack_person(room, user["id"], user["name"]))
        await slack.say("U1", mention(slack, "hello"), channel=CHANNEL)
        await until(lambda: heard)
        assert heard == [ours]


class TestWhoIsWho:

    async def test_guests_and_people_from_other_organisations_are_not_acted_for(self, slack, served, room):
        heard = []

        async def listens(tools, turn):
            heard.append(turn.person)

        await served(listens, greeted=False)
        slack.channels[CHANNEL]["members"] += ["U4", "U5"]
        for user in ("U4", "U5"):
            await slack.say(user, mention(slack, "show me the plan"), channel=CHANNEL)
        await until(lambda: len([m for m in slack.ephemeral if "only act for members" in m["text"]]) >= 2)
        await asyncio.sleep(0.5)
        assert len([m for m in slack.ephemeral if "only act for members" in m["text"]]) == 2, "once per person"
        assert heard == []

    async def test_someone_removed_from_the_tenant_is_refused(self, slack, served, room):
        heard = []

        async def listens(tools, turn):
            heard.append(turn.person)

        Identities(room.redis_store).deprovision(slack_person(room, "U2", "bob"))
        await served(listens, greeted=False)
        await slack.say("U2", mention(slack, "hi"), channel=CHANNEL)
        await until(lambda: any(m["to"] == "U2" for m in slack.ephemeral))
        assert heard == []


class TestWhoSeesWhat:

    async def test_a_private_room_is_not_shown_in_a_public_channel(self, slack, served, room):
        slack.channels[CHANNEL]["is_private"] = False
        await served()
        [notice] = slack.bot_messages(CHANNEL)
        assert "stopped posting the launch room here" in notice["text"]
        assert "anyone in the workspace can read this channel" in notice["text"]

    async def test_someone_joining_who_is_not_in_the_room_pauses_it_until_they_leave(
            self, slack, served, room):
        with_agents(room)
        heard = []

        async def listens(tools, turn):
            heard.append(turn.message)
            return "Here."

        slack.add_user("U6", name="dana")
        await served(listens)  # the message while paused never reaches the agent
        await slack.join("U6", CHANNEL)
        await until(lambda: any("stopped posting" in m["text"] for m in slack.bot_messages(CHANNEL)))
        assert "dana" in slack.bot_messages(CHANNEL)[-1]["text"].lower()

        ts = await slack.say("U1", mention(slack, "move it"), channel=CHANNEL)
        await until(lambda: any(m["to"] == "U1" and "not working on" in m["text"] for m in slack.ephemeral))
        assert heard == [], "the agent does nothing while the room may not be seen"

        await slack.leave("U6", CHANNEL)
        await until(lambda: any("carrying on" in m["text"] for m in slack.bot_messages(CHANNEL)))
        await slack.say("U1", mention(slack, "hello again"), channel=CHANNEL)
        await until(lambda: "Here." in [m["text"] for m in slack.bot_messages(CHANNEL)])
        assert ts not in [m.get("thread_ts") for m in slack.bot_messages(CHANNEL)]

    async def test_a_room_is_never_shown_to_another_organisation(self, slack, served, room):
        room.set_visibility("tenant", by=slack_person(room, "U1", "alice"))
        slack.channels[CHANNEL]["is_ext_shared"] = True
        await served()
        assert "shared with another organisation" in slack.bot_messages(CHANNEL)[0]["text"]

    async def test_work_on_someones_own_access_goes_to_them_alone(self, slack, served, room):
        with_agents(room, held=True)
        await served(asks_for_work)
        ts = await slack.say("U2", mention(slack, "summarise my inbox into the plan"), channel=CHANNEL)
        await until(lambda: [m for m in slack.messages if m["channel"] == "DU2" and m.get("blocks")])
        [dm] = [m for m in slack.messages if m["channel"] == "DU2" and m.get("blocks")]
        assert "Wednesday" in dm["blocks"][2]["text"]["text"]

        channel = [m for m in slack.bot_messages(CHANNEL)]
        assert not any("Wednesday" in json.dumps(m.get("blocks") or "") or "inbox." in m["text"]
                       for m in channel)
        assert any("used bob's private access" in m["text"] for m in channel)

        release = next(b for b in dm["blocks"][3]["elements"] if b["action_id"] == "room.release")
        await slack.click("U2", "room.release", release["value"], message_ts=dm["ts"])
        await until(lambda: any(m.get("blocks") for m in slack.thread(ts)))


    async def test_without_direct_messages_it_is_shown_to_them_alone_in_the_thread(self, slack, served, room):
        slack.direct_messages = False
        with_agents(room, held=True)
        await served(asks_for_work)
        ts = await slack.say("U2", mention(slack, "summarise my inbox"), channel=CHANNEL)
        await until(lambda: any(m["to"] == "U2" and m.get("blocks") for m in slack.ephemeral))
        held = next(m for m in slack.ephemeral if m["to"] == "U2" and m.get("blocks"))
        assert held["thread_ts"] == ts and "Wednesday" in json.dumps(held["blocks"])
        assert not any("Wednesday" in json.dumps(m.get("blocks") or "") for m in slack.bot_messages(CHANNEL))


class TestDelivery:

    async def test_a_message_not_recorded_is_not_acknowledged_and_comes_again(
            self, slack, served, room, monkeypatch):
        from jarviscore.room.conversation import RoomConversation

        heard = []

        async def listens(tools, turn):
            heard.append(turn.message)

        failures = [1]
        receive = RoomConversation.receive

        def flaky(self, *args, **kwargs):
            if failures:
                failures.pop()
                raise ConnectionError("Redis is unavailable")
            return receive(self, *args, **kwargs)

        monkeypatch.setattr(RoomConversation, "receive", flaky)
        await served(listens)
        await slack.say("U1", mention(slack, "status?"), channel=CHANNEL)
        await until(lambda: heard, timeout=5)
        await asyncio.sleep(1.0)
        assert heard == ["status?"], "handled once it was recorded, and once only"

    async def test_two_processes_share_the_events_and_post_each_update_once(self, slack, served, room):
        with_agents(room)
        heard = []

        async def listens(tools, turn):
            heard.append(turn.message)

        await served(*[listens] * 10)
        await served(*[listens] * 10, greeted=False)
        assert len(slack._sockets) == 2
        for i in range(6):
            await slack.say("U1", mention(slack, f"question {i}"), channel=CHANNEL)
        await until(lambda: len(heard) == 6)
        for i in range(4):
            room.note("ask.started", by="slack:T1.U3", by_name="carol", goal=f"task {i}", workflow_id=f"wf-{i}")
        await until(lambda: sum("carol asked" in m["text"] for m in slack.bot_messages(CHANNEL)) == 4)
        await asyncio.sleep(0.5)
        assert sorted(heard) == [f"question {i}" for i in range(6)]
        assert sum("carol asked" in m["text"] for m in slack.bot_messages(CHANNEL)) == 4
        assert len([m for m in slack.bot_messages(CHANNEL) if "is connected here" in m["text"]]) == 1
