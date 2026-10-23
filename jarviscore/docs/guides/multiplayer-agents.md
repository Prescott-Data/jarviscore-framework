---
icon: material/account-group-outline
title: "Build a Multiplayer Agent"
description: "Step by step: agents that do the work, a shared room, a room agent people talk to in Slack or your product, people in the loop, tests and production."
---

# Build a Multiplayer Agent

This guide builds a multiplayer agent step by step: a launch team and its agents writing a launch plan together, first in your own product, then in Slack. Each step ends with something you can run. For the model behind it, read [Multiplayer](../concepts/multiplayer.md).

By the end, anyone on the team asks for work in their own words, your agents propose the change in a thread, and people review and decide there, each as themselves. You write the agents; JarvisCore provides identity, permissions, the conversation, delivery and people in the loop.

!!! tip "See it finished first"
    The [multiplayer blueprint](https://github.com/Prescott-Data/jarviscore-agents/tree/main/multiplayer) in JarvisCore Agents is a complete version of what this guide builds: a marketing team, a strategist and a writer agent in one room, running in the Desk. Its [video](https://github.com/Prescott-Data/jarviscore-agents/releases/download/v1.0.0/jarviscore-multiplayer.mp4) shows a real run.

## Before you start

```bash
pip install "jarviscore-framework[redis,p2p]"
docker run -d -p 6379:6379 redis:7
```

Configure a language model the way you would for any AutoAgent (for example `AZURE_API_KEY` and `AZURE_ENDPOINT` in `.env`; see [Language Models](../concepts/language-models.md)). Rooms keep their state in the mesh's Redis, so set `REDIS_URL=redis://localhost:6379/0`.

## Step 1: the agents that do the work

Start with an agent that does useful work. Nothing in it is about multiplayer:

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

In a room, the agent gets the room's files and the tools to change them; you add nothing. A CustomAgent works too: its files are at `task["context"]["workspace_binding"]["path"]`, and whatever it changes there is its work:

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

## Step 2: people and a room

People are `Person`s in a **tenant** (the company or team using your product), and they come from whatever authenticates them: your app's login, or Slack. Two ways to make one:

```python
from jarviscore.room import Account, Identities, Person

# Your app manages its own users: use your ids directly.
alice = Person("acme", "u_1842", "Alice")

# Or let JarvisCore keep track of accounts on surfaces and the people they are.
people = Identities(mesh._redis_store)
alice = people.person_for(Account("acme", issuer="app", subject="u_1842", name="Alice"))
```

Use `Identities` when one person reaches the team through several surfaces; see [Rooms: people](rooms.md#people). Now create a room on a started mesh and add the team:

```python title="team.py"
import asyncio

from jarviscore import Mesh
from jarviscore.room import Person, Room
from agents import Writer

alice, bob, carol = (Person("acme", id, name) for id, name in
                     (("u_1842", "Alice"), ("u_2077", "Bob"), ("u_3310", "Carol")))


async def main():
    mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
    mesh.add(Writer)
    await mesh.start()

    room = Room.for_mesh(mesh, "launch", tenant="acme")
    await room.ensure({"plan.md": "# Launch plan\n\n## Risks\n\nTBD\n"}, by=alice)
    room.set_role(bob, "editor", by=alice)
    room.set_role(carol, "editor", by=alice)

    asked = await room.ask("Fill in the risks: the venue, the press embargo, support load",
                           asked_by=alice)
    for change in await room.diff(asked.proposal.id):
        print(change.unified())
    await room.accept(asked.proposal.id, by=bob)
    await mesh.stop()

asyncio.run(main())
```

What happened:

- The room is **private** to Alice, Bob and Carol until Alice opens it (`room.set_visibility("tenant", by=alice)`).
- `ask` ran a goal as Alice. The writer worked in its own copy of the files, and nothing changed in the room until Bob accepted the proposal.
- Had the writer used Alice's own mailbox, the proposal would have been **held** for her to release first. Owners name the systems the whole room may see with `room.set_shared_connectors([...], by=alice)`.

[Rooms](rooms.md) covers the full API. From here on, people talk instead of calling it.

## Step 3: a room agent people talk to

People don't call `room.ask`; they say "can you fill in the risks?" or "ship it". A `RoomAgent` understands that and acts on it as the person who spoke:

```python title="team.py"
from jarviscore.room import RoomAgent

mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
agent = mesh.add(RoomAgent)
mesh.add(Writer)
```

What it does with what people say:

| People say | The room agent |
|---|---|
| "Can you fill in the risks from Dana's brief?" | asks your agents, in the person's words |
| "Too wordy, one line per risk" | has the agents redo the proposal with exactly those words |
| A complete file pasted in a ``` block | files it, exactly as pasted, as that person's proposal |
| "Ship it", "No, the board fixed Tuesday", "Stop that, wrong brief" | prepares the decision for that person to confirm with one tap |
| "What does the plan say about support?", "What's running?", "Why didn't we move the launch?" | answers from the room's files, work and history |
| An answer to a question the agents asked | passes it on, in the person's words |
| "@carol are you around tomorrow?" | stays out of it |

It has no tool that accepts, rejects or approves. To make it sound like your team, subclass it:

```python
class LaunchDesk(RoomAgent):
    system_prompt = "You are the launch team's desk. Be brief; the team is busy."
    ask_options = {"timeout": 1800}   # how long a piece of work may take
```

## Step 4: in your own product

`RoomConversation` connects a room to a surface: it records messages, hands them to the room agent as their sender, posts progress and proposals in the right thread, and asks people to confirm. The surface itself only moves messages. For your product, implement `ChatSurface`:

```python title="web_surface.py"
from jarviscore.room import ChatSurface


class TeamPage(ChatSurface):
    """The launch room's page in our web app: a thread of messages per piece of work."""

    def __init__(self, db, room_page_id):
        self.db = db
        self.key = f"web:{room_page_id}"         # unique per place a room is shown

    async def say(self, thread, text, *, detail="", code="", to=None):
        # `to` means: show it to this person only.
        return await self.db.post(self.key, thread, text, detail=detail, code=code,
                                  visible_to=to.id if to else None)

    async def show_proposal(self, thread, text, diff, proposal_id, *, to=None, held=False):
        # Buttons: Accept and Full change; or, when held, Release and Discard.
        buttons = ["release", "discard"] if held else ["accept", "show_change"]
        return await self.db.post(self.key, thread, text, code=diff, buttons=buttons,
                                  target=proposal_id, visible_to=to.id if to else None)

    async def confirm(self, thread, decision, *, to):
        # Only `to` sees this, with Confirm and Cancel.
        return await self.db.post(self.key, thread, decision["summary"] + "?",
                                  buttons=["confirm", "cancel"], target=decision["id"],
                                  visible_to=to.id)
```

Then wire it to your web handlers:

```python title="app.py"
from jarviscore.room import RoomConversation

conversation = RoomConversation(room, agent, TeamPage(db, "launch"))
await conversation.start()                       # picks up where it left off
asyncio.create_task(conversation.follow())       # posts the room's progress, forever


@app.post("/rooms/launch/messages")
async def post_message(body: MessageIn, user=Depends(signed_in_user)):
    person = Person("acme", user.id, user.name)             # from your login, never from the body
    message_id = await db.save_message(user, body)          # your own id for it
    conversation.receive(person, body.text, message_id=message_id,
                         thread=body.thread, addressed=body.to_agent)
    asyncio.create_task(conversation.handle(message_id))
    return {"ok": True}


@app.post("/rooms/launch/buttons")
async def press(body: PressIn, user=Depends(signed_in_user)):
    person = Person("acme", user.id, user.name)
    await conversation.press(person, body.action, body.target, body.thread)
```

- **Identity comes from your login**, never from the message body.
- **`receive` before you respond.** Once it returns, the message will be handled even if the process stops; a repeated `message_id` is ignored.
- **Run as many processes as you like.** Messages are handled once, in order per thread, and each update is posted once.

Set `addressed=True` when someone speaks to the agent (an @-mention); replies in a thread the room started reach it on their own.

## Step 5: in Slack

`SlackApp` is a built-in surface using Socket Mode, so you need no public URL. One app serves every room of a tenant, each in its own channel.

**1. Create the Slack app** at [api.slack.com/apps](https://api.slack.com/apps): turn on Socket Mode and Interactivity; give the bot the scopes `chat:write`, `im:write`, `channels:read`, `groups:read`, `channels:history`, `groups:history`, `users:read` and `app_mentions:read`; subscribe to `app_mention`, `message.channels`, `message.groups`, `member_joined_channel`, `member_left_channel` and `channel_shared`. Install it, and create an app-level token with `connections:write`.

**2. Give the tokens to Nexus**, not your code:

```bash
jarviscore nexus register slack --auth-type api_key --api-key xoxb-... \
    --header-name Authorization --value-prefix "Bearer "
jarviscore nexus register slack_app --auth-type api_key --api-key xapp-... \
    --header-name Authorization --value-prefix "Bearer "
```

(With a [Nexus gateway](nexus.md), connect them there instead.)

**3. Serve the rooms:**

```python title="slack_desk.py"
from jarviscore.room.slack import SlackApp

agent = mesh.add(LaunchDesk)
mesh.add(Writer)
await mesh.start()

slack = SlackApp(agent, tenant="acme")
slack.connect(Room.for_mesh(mesh, "launch", tenant="acme"), "C0LAUNCH")   # a private channel
await slack.run()
```

Invite the bot to the channel; people mention it with what they need. Good to know:

- Full workspace members become people in the tenant on their first message. Guests, external users and bots are told the bot can only act for members.
- A private room is shown only in a private channel whose members are all in the room. If someone else joins, the room pauses there until they leave or are added.
- Held work goes to its asker in a direct message; confirmations are only visible to the person deciding.

`jarviscore room slack launch --channel C0LAUNCH --tenant acme` does all of this from the terminal, for trying it out.

## Step 6: when the agents need a person

Sometimes the work needs a person: a figure only finance has, or sign-off before an email goes out. Nothing extra to wire:

- **An agent asks for sign-off.** When an AutoAgent stops a step for a person ([HITL](hitl.md)), the step waits. The question appears in the work's thread, marked as needing sign-off. Someone says "yes, send it"; the room agent prepares the approval; they confirm; the step resumes with their answer.
- **The planner routes a step to people.** Put the team on the mesh as a [human peer](human-peers.md) with the capabilities only people have:

    ```python
    from jarviscore.human import HumanAgent

    mesh.add(HumanAgent("launch-team", ["approval", "legal-review"], channel=None))
    ```

    A plan that needs `legal-review` routes that step to the team. The question appears in the work's thread, and the first editor to answer it answers for the team, in their own words.

A room shows only questions from its own work, without anyone's private details.

## Step 7: test it without a model or a workspace

`MemorySurface` keeps everything posted, and `ScriptedRoomAgent` runs the real room tools from a script instead of a model. You need Redis and `pytest-asyncio`:

```python title="test_launch_room.py"
import uuid

import pytest

from jarviscore.room import CONFIRM, Person, Room, RoomConversation
from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent

alice = Person("acme", "u_1842", "Alice")
carol = Person("acme", "u_3310", "Carol")


@pytest.mark.asyncio
async def test_carol_ships_it():
    room = Room.open(f"launch-{uuid.uuid4().hex[:8]}", tenant="acme",
                     redis_url="redis://localhost:6379/0")
    await room.ensure({"plan.md": "# Launch plan\n"}, by=alice)
    room.set_role(carol, "editor", by=alice)
    proposal = await room.propose({"plan.md": "# Launch plan\n\nShip on Tuesday.\n"},
                                  by=alice, title="Set the date")

    # What the model would do with "looks good, ship it": prepare the decision.
    async def ship_it(tools, turn):
        await tools.prepare_decision(action="accept", target=proposal.id)
        return "Tap Confirm and it's in."

    surface = MemorySurface()
    conversation = RoomConversation(room, ScriptedRoomAgent(ship_it), surface)
    await conversation.start()

    await conversation.hear(carol, "looks good, ship it", thread="t1", message_id="m1",
                            addressed=True)
    assert room.proposal(proposal.id).status == "open"     # nothing from text alone

    [decision] = surface.confirmations
    await conversation.press(carol, CONFIRM, decision["id"], "t1")
    assert room.proposal(proposal.id).status == "accepted"
```

For Slack, `jarviscore.testing.slack.FakeSlack` serves Slack's Web API and Socket Mode on a local port; point the `slack` and `slack_app` Nexus connections at it.

## Step 8: to production

- **Redis**: one managed Redis with persistence, shared by every process.
- **Files**: kept in the mesh's blob storage; `STORAGE_BACKEND=azure` for large media.
- **Processes**: run surfaces and agents on as many processes and nodes as you like; work a stopped process started is finished by another.
- **Tenants**: one per customer of your product.
- **People leaving**: `Identities.deprovision(person)` ends everything they could do.
- **Spend**: cap model use per tenant and per person with `Spending.set_caps` ([Rooms: spending](rooms.md#spending)); `ask_options={"timeout": ...}` bounds each piece of work.
- **Memory**: run [Athena](../concepts/memory.md#setting-up-athena) for memory shared across machines; without it, room memory stays on the machine that ran the work.
- **Audit**: export `room.audit()` and `Identities.log(tenant)` if you keep audit records elsewhere.

## Where to go next

- [Rooms](rooms.md): the room API, people and roles, private access, merging and history
- [Chat Surfaces](chat-surfaces.md): the surface contract in full, and Slack in detail
- [People as Peers](human-peers.md): people the planner routes work to
- [Multiplayer API](../reference/multiplayer-api.md): every class and method
