---
icon: material/account-group-outline
title: "Build a Multiplayer Agent"
description: "Step by step: the agents that do the work, a shared room, the team on the mesh, a room agent people talk to in plain words, Slack, tests without a model, and what changes for production."
---

# Build a Multiplayer Agent

This guide builds a working multiplayer agent from nothing: a launch team and its agents writing a launch plan and an announcement email together in Slack. Each step adds one piece and ends with something you can run. If you haven't yet, read [Multiplayer](../concepts/multiplayer.md) first for the model behind it.

By the end:

- Anyone on the team mentions the bot in Slack with what they need, in their own words.
- Your agents do the work on the team's shared files and propose the change in a thread.
- People review it there. They say what to change, approve it, turn it down, or paste their own version, and the agent acts on what they meant, as them.
- When the agents need a person, for a confirmation or a decision, they ask in that thread.
- Every decision is remembered with who made it and why.

You write two things: the agents that do the work, and, if you want, how the room agent speaks for your team. JarvisCore provides the rest.

## Before you start

```bash
pip install "jarviscore-framework[redis,p2p]"
docker run -d -p 6379:6379 redis:7
```

Configure a language model the way you would for any AutoAgent (for example `AZURE_API_KEY` and `AZURE_ENDPOINT` in `.env`; see [Language Models](../concepts/language-models.md)). Rooms keep their state in the mesh's Redis, so set `REDIS_URL=redis://localhost:6379/0`.

## Step 1: the agents that do the work

A multiplayer agent is first an agent that does useful work. Here it is a writer that edits the team's documents. Nothing in it is about multiplayer:

```python title="agents.py"
from jarviscore.profiles import AutoAgent


class Writer(AutoAgent):
    role = "writer"
    capabilities = ["writing", "editing"]
    system_prompt = """
    You write and edit a launch team's working documents: plans, briefs and emails.
    Work in the files you are given. Keep the team's structure and voice.
    """
```

When a step of work in a room reaches this agent, the Kernel gives it the room's files and the tools to read and change them, whichever of its sub-agents does the step. You don't add anything for that.

A CustomAgent works the same way, with plain Python. Its step finds the files at `task["context"]["workspace_binding"]["path"]`, and whatever it changes there is its work:

```python
from pathlib import Path
from jarviscore.profiles import CustomAgent


class Formatter(CustomAgent):
    role = "formatter"
    capabilities = ["formatting"]

    async def execute_task(self, task):
        root = Path(task["context"]["workspace_binding"]["path"])
        plan = root / "plan.md"
        plan.write_text(plan.read_text().replace("\t", "    "))
        return {"status": "success", "output": "Normalised the indentation in plan.md"}
```

## Step 2: a room for the shared work

A room holds the files the team works on and every change to them. Create it on a mesh, then ask the agents for something:

```python title="step2.py"
import asyncio
from pathlib import Path

from jarviscore import Mesh
from jarviscore.room import Room
from agents import Writer


async def main():
    mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
    mesh.add(Writer)
    await mesh.start()

    room = Room.for_mesh(mesh, "launch")
    await room.ensure({
        "plan.md": Path("plan.md").read_text(),
        "brief.md": Path("brief.md").read_text(),
    }, by="alice")

    asked = await room.ask("Fill in the Risks section of plan.md from the concerns in brief.md",
                           asked_by="alice")
    for change in await room.diff(asked.proposal.id):
        print(change.unified())
    await room.accept(asked.proposal.id, by="bob")
    print(f"The room is at version {room.head().version}")
    await mesh.stop()

asyncio.run(main())
```

`room.ask` runs the request as a normal JarvisCore goal. The planner breaks it into steps, the writer takes them, and each step works on its own copy of the room's current files. The result is a **proposal**: nothing in the room changes until someone accepts it. If the room changed in the meantime, accepting merges the proposal over the newer work, and if two changes really clash, it stops with a conflict instead of overwriting anyone.

Notice `asked_by="alice"` and `by="bob"`. Every request and decision belongs to a person. The steps of Alice's request use Alice's own connected accounts, and the room's history records that Bob accepted it. See [Rooms](rooms.md) for proposals, merging, roles and history in full.

## Step 3: the team as a peer

Some work needs a person: a confirmation, a sign-off, a judgement call. Put the team on the mesh as a `HumanAgent`, and the planner can route those steps to them:

```python
from jarviscore.human import HumanAgent

mesh.add(HumanAgent("team", ["approval"], channel=None))
```

Now a request such as "Draft the waitlist email in email.md. Someone on the team has to confirm the send date first" plans a step for `team`. That step becomes a question in the HITL store and waits for an answer. The rest of the work continues once someone answers:

```bash
jarviscore human inbox team
jarviscore human answer hitl-20261018-153012-1a2b3c4d "Wednesday 14 October, 09:30 Nairobi time"
```

In Step 5 the same question appears in Slack instead, in the thread of the work that raised it. See [People as Peers](human-peers.md) for individual people, terminals and decisions.

## Step 4: a room agent people talk to

People don't want to call `room.accept`. They want to say "looks good, ship it". A `RoomAgent` is the agent they talk to. It reads each message with its context and acts on it with the room's own operations, as the person who spoke:

```python
from jarviscore.room import RoomAgent

room_agent = mesh.add(RoomAgent)
await mesh.start()
room = Room.for_mesh(mesh, "launch")

turn = await room_agent.converse(room, "alice", "Can you fill in the risks from Dana's brief?")
print(turn.replies)   # ["I've asked the agents to fill in the Risks section from Dana's brief. ..."]
```

The room agent is an AutoAgent with one extra Kernel role, `room`. It reasons, remembers and is traced like any other agent. Its tools are what a person can do in a room: ask the agents for work, request changes to a proposal with their feedback, accept, reject, propose their own version of a file, answer a question the agents asked, and look at the files, the changes and the history. It decides what a message means and whether it is for it at all, so people can keep talking to each other in the same thread. Its final answer is its reply.

`converse` returns once the message is handled. Work it starts carries on after it, and the progress and proposal are posted to wherever the conversation is shown (next step).

To make it speak for your team, subclass it. Your `system_prompt` leads its instructions, and `subagent_class` lets you give it tools of your own:

```python
from jarviscore.room import RoomAgent, RoomSubAgent


class LaunchDeskTools(RoomSubAgent):
    def setup_tools(self):
        super().setup_tools()
        self.register_tool("launch_calendar", self._tool_launch_calendar,
                           "Dates already booked for launches. Params: {}", phase="thinking")

    async def _tool_launch_calendar(self, **_):
        return {"status": "success", "booked": ["2026-10-14", "2026-10-21"]}


class LaunchDesk(RoomAgent):
    system_prompt = """
    You work with the Orbit launch team. Dana owns marketing decisions and Sam owns support.
    Dates are in Nairobi time.
    """
    subagent_class = LaunchDeskTools
```

## Step 5: in Slack

Slack is supported natively. A room is served in a channel: a mention starts a thread, the work happens in it, and people reply there in their own words.

**Create the Slack app.** In your Slack workspace, create an app with:

- **Socket Mode** on. Slack then pushes events to your process, so it needs no public URL.
- The bot scopes `chat:write`, `channels:history`, `groups:history`, `users:read` and `app_mentions:read`.
- The event subscriptions `app_mention`, `message.channels` and `message.groups`.
- **Interactivity** on, for the Accept and Full change buttons.

Install it to the workspace and invite the bot to the team's channel.

**Connect it through Nexus.** JarvisCore never holds Slack tokens in your code or environment. They live in Nexus, like every other credential. The bot token signs the Web API calls, and the app-level token opens the Socket Mode connection:

```bash
jarviscore nexus register slack --auth-type api_key --api-key xoxb-... \
    --header-name Authorization --value-prefix "Bearer "
jarviscore nexus register slack_app --auth-type api_key --api-key xapp-... \
    --header-name Authorization --value-prefix "Bearer "
```

With a Nexus gateway, connect `slack` and `slack_app` there instead. See [Nexus Credentials](nexus.md).

**Serve the room.** From the terminal, on any machine that reaches the mesh:

```bash
jarviscore room slack launch --channel C0123ABC --seed 10.0.0.5:7949 --capabilities approval
```

This starts a node with a room agent, and a HumanAgent named `team` (change it with `--people`) standing for the people in the channel, and joins the mesh at `--seed` so planners can route steps to them. Or in your own process, with your own room agent:

```python
from jarviscore.room import Room
from jarviscore.room.slack import SlackRoom

desk = mesh.add(LaunchDesk)
mesh.add(HumanAgent("team", ["approval"], channel=None))
await mesh.start()
await SlackRoom(Room.for_mesh(mesh, "launch"), desk, "C0123ABC", people="team").run()
```

The person who posts in Slack is who the agent acts as. By default a room member is their Slack handle. Map Slack users to the identities your organisation uses with `members={"U0123ABC": "alice@acme.com"}`. See [Chat Surfaces](chat-surfaces.md) for everything Slack does, and for adding a surface of your own.

## Step 6: test it without a model or a workspace

Two test helpers ship with JarvisCore. `ScriptedRoomAgent` runs the real room tools from a script you write instead of a model, so a test decides what each message means and checks what the room does. `MemorySurface` keeps what the conversation posts:

```python title="test_launch_room.py"
from jarviscore.room import RoomConversation
from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent


async def test_a_reviewer_ships_the_proposal(room):          # a Room fixture
    async def ships_it(tools, turn):
        await tools._tool_accept()
        return "Accepted."

    surface = MemorySurface()
    conversation = RoomConversation(room, ScriptedRoomAgent(ships_it), surface)
    await conversation.start()
    await conversation.hear("bob", "ship it", thread="m1", message_id="m2")
    assert room.head().updated_by == "bob"
```

For Slack itself, `jarviscore.testing.slack.FakeSlack` speaks Slack's Web API and Socket Mode protocol on a local port. Point the `slack` and `slack_app` Nexus connections at it, and `SlackRoom` runs against it exactly as it would against Slack.

## Step 7: to production

The pieces above run unchanged in production. What changes is where they run and what you configure.

**Topology.** Run your working agents on as many nodes as you need, all on one mesh with one Redis. Run the room's surface (`jarviscore room slack`, or your `SlackRoom`) as its own small service. It holds the room agent and the people's HumanAgent, and joins the mesh with `--seed`. Nodes find each other over [P2P](../concepts/p2p.md). Rooms, proposals, history and work all live in Redis, so any node can serve any room.

**Files.** Set `STORAGE_BACKEND=redis` so every node sees the same files through the same Redis (single files up to 32 MB by default), or `azure` for large files. See [Configuration](../reference/configuration.md).

**Identity and access.** Each person connects their own accounts in Nexus, in their own workspace, under the identity your surface reports (`members`). Steps of their requests then use their access, and provider audit logs show them. Never set `asked_by` or `by` from text a user typed.

**Who may do what.** A room is open to everyone in it until its creator adds members. Then viewers watch, editors ask and decide, and owners manage members. See [Who can do what](rooms.md#who-can-do-what).

**Memory.** Rooms keep their decision history in Redis without anything else. For semantic memory shared by every agent working in a room, configure [Athena](../concepts/memory.md) and `Mesh(config={"memory_scope_field": "room_id"})` on your agent nodes. `jarviscore room slack` scopes the room agent's memory this way already.

**Limits and time.** Bound how long a request's work may run with `RoomAgent.ask_options = {"timeout": 1800}` (seconds; `jarviscore room slack --timeout` sets it, 30 minutes by default). A question to people waits up to `HumanAgent.answer_timeout` (an hour by default) before its step fails.

**Seeing what happened.** Every message to the room agent runs under the workflow `room-<room>-conversation` and every request under its own workflow, so the usual [traces and observability](observability.md) apply. `jarviscore room watch ROOM` follows a room from a terminal.

## Where to go next

- [Rooms](rooms.md): proposals, merging, conflicts, roles, history, and working by hand
- [People as Peers](human-peers.md): individuals on the mesh, and how they answer
- [Chat Surfaces](chat-surfaces.md): Slack in depth, and your own surface
- [Multiplayer API](../reference/multiplayer-api.md): every class and method
