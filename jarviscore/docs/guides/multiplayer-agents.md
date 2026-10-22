---
icon: material/account-group-outline
title: "Build a Multiplayer Agent"
description: "Step by step: agents that do the work, a shared room, a room agent people talk to in Slack or your product, people in the loop, tests and production."
---

# Build a Multiplayer Agent

This guide builds a working multiplayer agent from nothing: a launch team and its agents writing a launch plan together, first in your own product and then in Slack. Each step adds one piece and ends with something you can run. If you haven't yet, read [Multiplayer](../concepts/multiplayer.md) first for the model behind it.

By the end:

- Anyone on the team asks for something in their own words, where the team already talks.
- Your agents do the work on the team's shared files and propose the change in a thread.
- People review it there. They say what to change, paste their own version, or decide, and the agent acts on what they meant, as them. Decisions take one tap from the person who made them.
- When the agents need a person, they ask in that thread.
- Work that used someone's own access is shown to them first.
- Every decision is kept with who made it and why.

You write two things: the agents that do the work, and, if you want, how the room agent speaks for your team. JarvisCore provides the rest: identity, permissions, the conversation, delivery, people in the loop and the guarantees behind them.

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

## Step 2: people and a room

Everything multiplayer happens in a **tenant**: the company or team using your product. People are `Person`s in a tenant, and a room belongs to one tenant.

Where do people come from? From whatever authenticates them. Your application already knows who is signed in; Slack knows who posted. You turn that into a `Person`, in one of two ways:

```python
from jarviscore.room import Account, Identities, Person

# Your app manages its own users: use your ids directly.
alice = Person("acme", "u_1842", "Alice")

# Or let JarvisCore keep track of accounts on surfaces and the people they are.
people = Identities(mesh._redis_store)
alice = people.person_for(Account("acme", issuer="app", subject="u_1842", name="Alice"))
```

`Identities` is what the Slack surface uses, so it is the right choice when one person reaches the team through more than one surface: link their accounts and they are one person with one set of roles. See [Rooms: people](rooms.md#people) for linking and removing people.

A room holds the files the team works on and every change to them. Create it on a started mesh, as the person who owns it, and add the team:

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

- The room is **private**: only Alice (its owner), Bob and Carol can see it. `room.set_visibility("tenant", by=alice)` would open it to everyone in Acme.
- `ask` ran an ordinary goal as Alice. The planner chose the writer; the writer worked in its own copy of the room's files; its change came back as a proposal. Nothing changed in the room until Bob accepted it.
- Had the writer read Alice's own mailbox through Nexus on the way, the proposal would have been **held** for Alice: Bob could not see or accept it until she released it (`room.release(id, by=alice)`). Owners name the systems everyone in a room may see with `room.set_shared_connectors(["google_drive"], by=alice)`.

[Rooms](rooms.md) covers the room API in full. From here on, people talk instead of calling it.

## Step 3: a room agent people talk to

People don't call `room.ask`. They say "can you fill in the risks?", "too wordy", "ship it", or "why did we drop the venue risk?". A `RoomAgent` understands that and acts on it with the room's own operations, as the person who spoke:

```python title="team.py"
from jarviscore.room import RoomAgent

mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
agent = mesh.add(RoomAgent)
mesh.add(Writer)
```

That is all the room agent needs. It is an AutoAgent with one more Kernel role, `room`, whose tools are the room's actions:

| People say | The room agent |
|---|---|
| "Can you fill in the risks from Dana's brief?" | asks your agents, in the person's words |
| "Too wordy, one line per risk" | has the agents redo the proposal with exactly those words |
| A complete file pasted in a ``` block | files it, exactly as pasted, as that person's proposal |
| "Ship it", "No, the board fixed Tuesday", "Stop that, wrong brief" | prepares the decision for that person to confirm with one tap |
| "What does the plan say about support?", "What's running?", "Why didn't we move the launch?" | answers from the room's files, work and history |
| An answer to a question the agents asked | passes it on, in the person's words |
| "@carol are you around tomorrow?" | stays out of it |

It cannot accept, reject or approve anything itself: it has no tool that does. Make it sound like your team with `system_prompt`, or give it more tools by subclassing `RoomSubAgent` and setting `subagent_class` (see [Custom Subagents](custom-subagents.md)):

```python
class LaunchDesk(RoomAgent):
    system_prompt = "You are the launch team's desk. Be brief; the team is busy."
    ask_options = {"timeout": 1800}   # how long a piece of work may take
```

## Step 4: in your own product

A room's conversation needs a place to happen. `RoomConversation` connects one room to one surface and does everything multiplayer about it: it records each message durably, hands it to the room agent as the person who sent it, posts the work's progress and proposals in the right thread, asks people to confirm decisions, shows held work only to its asker, and checks who can see the surface before it posts anything.

A surface only moves messages. For your product, implement `ChatSurface`:

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

Your page shows each person what everyone sees plus what is `visible_to` them, so `audience` can keep its default (anyone may be shown it). Wire it to your web handlers:

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

Three things matter here:

- **Who the person is comes from your login.** The room agent acts as that person, with their room role. A message body naming someone else changes nothing.
- **`receive` before you answer the request.** Once it returns, the message will be handled even if this process stops right after; a second `receive` of the same `message_id` is ignored. `handle` handles messages in order within each thread, across all your processes. (`hear` does both, for when you don't need the split.)
- **Run as many processes as you like.** Every one can receive and handle messages. Only one at a time posts updates (`follow` holds a lease), and each update is posted once.

A person sends `addressed=True` when they speak to the agent, for example with an @-mention or a "Ask the agents" box. Replies in a thread the room started reach the agent on their own; other conversation in your page does not.

## Step 5: in Slack

JarvisCore supports Slack natively: `SlackApp` is the surface, Socket Mode included, so you need no public URL. One `SlackApp` serves every room of a tenant in its Slack workspace, each in its own channel.

**Create the Slack app** at [api.slack.com/apps](https://api.slack.com/apps): turn on Socket Mode and Interactivity; give the bot the scopes `chat:write`, `im:write`, `channels:read`, `groups:read`, `channels:history`, `groups:history`, `users:read` and `app_mentions:read`; subscribe to `app_mention`, `message.channels`, `message.groups`, `member_joined_channel`, `member_left_channel` and `channel_shared`. Install it, and create an app-level token with `connections:write`.

**Give Nexus the tokens**, never your code. Slack calls go through Nexus with the workspace's bot token, and Socket Mode with the app-level token:

```bash
jarviscore nexus register slack --auth-type api_key --api-key xoxb-... \
    --header-name Authorization --value-prefix "Bearer "
jarviscore nexus register slack_app --auth-type api_key --api-key xapp-... \
    --header-name Authorization --value-prefix "Bearer "
```

(With a [Nexus gateway](nexus.md), connect them there instead.)

**Serve the rooms:**

```python title="slack_desk.py"
from jarviscore.room.slack import SlackApp

agent = mesh.add(LaunchDesk)
mesh.add(Writer)
await mesh.start()

slack = SlackApp(agent, tenant="acme")
slack.connect(Room.for_mesh(mesh, "launch", tenant="acme"), "C0LAUNCH")   # a private channel
await slack.run()
```

Invite the bot to the channel. People mention it with what they need, and the thread that follows is where the work happens.

**Who is who in Slack.** A full member of the workspace is a person in the tenant; their first message makes them one, through `Identities`. Guests, people from other organisations in shared channels, and bots are not, and the bot tells them it can only act for the workspace's members. If your product has its own directory, pass `identify=` to map each Slack user to your `Person`.

**Who sees what in Slack.** A private room is shown only in a private channel whose members are all in the room, and no room is shown in a channel shared with another organisation. Add the room's members to the channel and the room's people to the room. If someone joins the channel who is not in the room, the bot stops posting the room there, and says so, until they leave or are added. Work held for someone goes to them in a direct message with Release and Discard buttons (or, without `im:write`, as a message only they see in the thread). Confirmations are always messages only the person deciding sees.

`jarviscore room slack launch --channel C0LAUNCH --tenant acme` does all of this from the terminal, for trying it out.

## Step 6: when the agents need a person

Sometimes the work needs a person: a figure only finance has, a sign-off before an email goes to 40,000 people. You don't wire anything for the room to handle this.

- **An agent asks for sign-off.** When an AutoAgent stops a step for a person ([HITL](hitl.md)), the step waits. The question appears in the work's thread, marked as needing sign-off. Someone says "yes, send it"; the room agent prepares the approval; they confirm; the step resumes with their answer.
- **The planner routes a step to people.** Put the team on the mesh as a [human peer](human-peers.md) with the capabilities only people have:

    ```python
    from jarviscore.human import HumanAgent

    mesh.add(HumanAgent("launch-team", ["approval", "legal-review"], channel=None))
    ```

    A plan that needs `legal-review` routes that step to the team. The question appears in the work's thread, and the first editor to answer it answers for the team, in their own words.

Questions are scoped: a room shows only questions raised by its own work, in its own tenant. If the work used someone's private access, the question is asked without the private details.

## Step 7: test it without a model or a workspace

`jarviscore.testing.rooms` has a `MemorySurface` that keeps everything posted (including what was shown to one person, and confirmations), and a `ScriptedRoomAgent` that runs the real room tools from a script instead of a model. Tests decide what each message means and check what the room and the surface do:

```python title="test_launch_room.py"
from jarviscore.room import CONFIRM, RoomConversation
from jarviscore.testing.rooms import MemorySurface, ScriptedRoomAgent


async def ship_it(tools, turn):
    await tools._tool_prepare_decision(action="accept")
    return "Tap Confirm and it's in."


async def test_carol_ships_it(room, proposal_in_thread, carol):
    surface = MemorySurface()
    conversation = RoomConversation(room, ScriptedRoomAgent(ship_it), surface)
    await conversation.start()

    await conversation.hear(carol, "looks good, ship it", thread="t1", message_id="m2")
    assert room.proposal(proposal_in_thread).status == "open"      # nothing from text alone

    [decision] = surface.confirmations
    await conversation.press(carol, CONFIRM, decision["id"], "t1")
    assert room.proposal(proposal_in_thread).status == "accepted"
```

`jarviscore.testing.slack.FakeSlack` speaks Slack's Web API and Socket Mode on a local port, with Slack's behaviour where correctness depends on it: events shared between connections, redelivery of unacknowledged events, private and shared channels, guests, and messages only one person sees. Point the `slack` and `slack_app` Nexus connections at it (with a `base_url` of its address) and `SlackApp` runs against it unchanged.

## Step 8: to production

- **Redis** holds rooms, people, conversations and questions; every process of your deployment uses the same one. Use a managed Redis with persistence.
- **File storage**: rooms keep file contents in the mesh's blob storage. Redis suits documents and code; set `STORAGE_BACKEND=azure` for large media.
- **Processes**: run the surface (your web app, or `SlackApp`) in as many processes as you like, and your agents on as many nodes as you like. Messages are handled once, updates posted once, and work started by a process that stops is finished by another (`RoomConversation.start` picks it up).
- **Tenants**: give each customer of your product its own tenant. A tenant's people, rooms and questions never reach another.
- **People leaving**: `Identities.deprovision(person)` ends everything they could do at once.
- **Shared systems**: decide per room which connected systems everyone may see (`set_shared_connectors`). Anything else stays with the person whose access it was.
- **Spend**: model use is charged to the person each piece of work is for; cap it per tenant and per person with `Spending.set_caps` (see [Rooms: spending](rooms.md#spending)). Each piece of work also runs under the mesh's workflow budget (see [Goal Execution](goal-execution.md)), and `ask_options={"timeout": ...}` bounds how long it may run: work that times out is stopped, not left running.
- **Memory**: run [Athena](../concepts/memory.md#setting-up-athena) and set `ATHENA_URL`; every room then has a shared memory in its tenant, with private memory for what came from someone's own access. Check Athena's log once that it summarises: without a working chat and embedding model it keeps events but makes nothing searchable.
- **Audit**: `room.audit()` and `Identities.log(tenant)` are what an auditor asks for; export them on a schedule if you keep audit records elsewhere.

## Where to go next

- [Rooms](rooms.md): the room API, people and roles, private access, merging and history
- [Chat Surfaces](chat-surfaces.md): the surface contract in full, and Slack in detail
- [People as Peers](human-peers.md): people the planner routes work to
- [Multiplayer API](../reference/multiplayer-api.md): every class and method
