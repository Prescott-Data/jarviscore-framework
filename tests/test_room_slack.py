"""A room in a Slack channel, with Slack reached only through Nexus."""

import asyncio

import fakeredis
import pytest

from jarviscore.nexus import store as vault
from jarviscore.room import Room
from jarviscore.room.slack import (
    ACCEPT_ACTION,
    CHANGE_ACTION,
    SlackApi,
    SlackError,
    SlackRoom,
    escape,
    unescape,
)
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore
from jarviscore.testing.rooms import ScriptedRoomAgent
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


@pytest.fixture
async def room(tmp_path):
    store = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    room = Room("launch", blob_storage=LocalBlobStorage(str(tmp_path / "blobs")), redis_store=store)
    await room.ensure({"plan.md": PLAN}, by="alice")
    return room


def with_agents(room):
    async def ask(goal, *, asked_by, revision_of="", workflow_id="", **options):
        head = room.head()
        room.note("ask.started", by=asked_by, goal=goal, workflow_id=workflow_id, version=head.version)
        proposal = await room.propose(
            {"plan.md": PLAN.replace("Tuesday", "Wednesday <b> & co")}, author="writer",
            asked_by=asked_by, title=goal, base_version=head.version, workflow_id=workflow_id)
        room.note("ask.finished", by=asked_by, workflow_id=workflow_id, status="completed",
                  summary="Moved it.", proposal=proposal.id)

    room.mesh = object()
    room.ask = ask


async def asks_for_work(tools, turn):
    await tools._tool_ask_agents(goal="Move the announcement")
    return "On it, <working> & will post here."


@pytest.fixture
async def served(slack, nexus, room):
    """A SlackRoom on its own Nexus-backed API, running as it would in production."""
    with_agents(room)
    started = []

    async def serve(*scripts, **options):
        agent = ScriptedRoomAgent(*scripts)
        api = await SlackApi.through_nexus(None, api_url=slack.api_url)
        bridge = SlackRoom(room, agent, CHANNEL, api=api, poll_interval=0.02, **options)
        started.append(asyncio.create_task(bridge.run()))
        await slack.connected()
        await until(lambda: slack.bot_messages(CHANNEL))
        return bridge, agent

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
        assert api.bot_user_id == "UBOT", "the fake only answers the right bot token"
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
            async for envelope in api.events():
                received.append(envelope)

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
        await served(asks_for_work)
        ts = await slack.say("U1", mention(slack, "can we <launch> wednesday?"), channel=CHANNEL)
        await until(lambda: any(m.get("blocks") for m in slack.thread(ts)))

        replies = texts(slack, ts)
        assert replies[0] == "On it, &lt;working&gt; &amp; will post here."
        blocks = proposal_message(slack, ts)["blocks"]
        assert "+- Announce on Wednesday &lt;b&gt; &amp; co" in blocks[1]["text"]["text"]
        assert [a["action_id"] for a in blocks[2]["elements"]] == [ACCEPT_ACTION, CHANGE_ACTION]
        await until(lambda: any("\n>Moved it." in t for t in texts(slack, ts)))
        assert room.proposals("open")[0].asked_by == "alice"

    async def test_a_reply_reaches_the_agent_as_the_slack_user_with_the_thread(self, slack, served, room):
        heard = []

        async def accepts(tools, turn):
            heard.append(turn)
            await tools._tool_accept()

        _, agent = await served(asks_for_work, accepts)
        ts = await slack.say("U1", mention(slack, "move it"), channel=CHANNEL)
        await until(lambda: any(m.get("blocks") for m in slack.thread(ts)))
        await slack.say("U2", "looks great, ship it", channel=CHANNEL, thread_ts=ts)
        await until(lambda: room.head().version == 2)

        assert room.head().updated_by == "bob"
        assert heard[0].person == "bob" and heard[0].message == "looks great, ship it"
        assert heard[0].history[0] == {"person": "alice", "text": "move it"}
        await until(lambda: any(t.startswith("✓ bob accepted") for t in texts(slack, ts)))

    async def test_the_buttons(self, slack, served, room):
        await served(asks_for_work)
        ts = await slack.say("U1", mention(slack, "move it"), channel=CHANNEL)
        await until(lambda: any(m.get("blocks") for m in slack.thread(ts)))
        message = proposal_message(slack, ts)
        proposal = room.proposals("open")[0].id
        await slack.click("U3", CHANGE_ACTION, proposal, message_ts=message["ts"])
        await until(lambda: any("The full change in" in t for t in texts(slack, ts)))
        await slack.click("U3", ACCEPT_ACTION, proposal, message_ts=message["ts"])
        await until(lambda: room.head().version == 2)
        assert room.head().updated_by == "carol"

    async def test_slack_users_can_be_mapped_to_room_members(self, slack, served, room):
        heard = []

        async def listens(tools, turn):
            heard.append(turn.person)

        await served(listens, members={"U1": "alice@acme.com"})
        await slack.say("U1", mention(slack, "hello"), channel=CHANNEL)
        await until(lambda: heard)
        assert heard == ["alice@acme.com"]

    async def test_only_messages_for_the_room_reach_the_agent_and_a_mention_once(self, slack, served):
        heard = []

        async def listens(tools, turn):
            heard.append(turn.message)

        _, agent = await served(listens)
        await slack.say("U2", "lunch anyone?", channel=CHANNEL)
        await slack.say("U2", mention(slack, "hi"), channel="C-other")
        await slack.say("U2", mention(slack, "status please"), channel=CHANNEL)
        await until(lambda: heard)
        await asyncio.sleep(0.3)
        assert heard == ["status please"], "once, though Slack sends a mention twice"

    async def test_the_channel_is_greeted_once(self, slack, nexus, room):
        with_agents(room)
        for _ in range(2):
            api = await SlackApi.through_nexus(None, api_url=slack.api_url)
            await SlackRoom(room, ScriptedRoomAgent(), CHANNEL, api=api).start()
        assert len(slack.bot_messages(CHANNEL)) == 1
        assert "The launch room is connected here" in slack.bot_messages(CHANNEL)[0]["text"]
