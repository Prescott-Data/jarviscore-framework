---
icon: material/forum-outline
title: "Chat Surfaces: Rooms Where Your Team Talks"
description: "Serve a room where people already work: Slack natively, through Nexus with no tokens in your code, or any other chat or product UI through the ChatSurface interface."
---

# Chat Surfaces

A multiplayer agent is used where the team already talks. A chat surface connects a [room](rooms.md) to such a place. Requests become threads, the work's progress and proposals are posted in them, the agents' questions to people are asked there, and everything people say there goes to the [room agent](multiplayer-agents.md#step-4-a-room-agent-people-talk-to), which acts on it as them.

JarvisCore supports Slack natively. Anything else, such as Microsoft Teams, Discord or your own product, is a small adapter you write. The multiplayer behavior lives in `RoomConversation`, which every surface shares; a surface only moves messages.

## What people can do

In a room's channel, people talk in their own words. There is no command syntax:

| They say | The room agent |
|---|---|
| "@bot can you fill in the risks from Dana's brief?" | Asks the agents, as them; the work and its proposal appear in that thread |
| "Too wordy. One line per risk, and say Sam handles support." | Turns the proposal down with their words as the reason, and has it redone |
| "Looks good, ship it" (or the Accept button) | Accepts the proposal, as them |
| "No, Dana is rewriting the plan herself" | Rejects it, with that reason |
| A pasted file in a code block: "here's mine" | Proposes it, exactly as pasted, as theirs; accepting it closes the agents' version |
| "Why didn't we move the launch?" | Answers from the room's history and files |
| An answer to a question the agents asked | Passes it to the agents, from them |
| "@carol can you look at this tomorrow?" | Nothing: it was for Carol |

When it is unsure what someone means, especially before accepting or rejecting, it asks. Roles still apply: a viewer who says "ship it" is told they can't accept, and why.

## Slack

### Set up the Slack app

Create an app in your Slack workspace with:

- **Socket Mode** on. Slack pushes events over a connection your process opens, so it needs no public URL and runs anywhere, a laptop included.
- The bot scopes `chat:write`, `channels:history`, `groups:history`, `users:read` and `app_mentions:read`.
- The event subscriptions `app_mention`, `message.channels` and `message.groups`.
- **Interactivity** on, for the Accept and Full change buttons on proposals.

Install it to the workspace, note the bot token (`xoxb-…`) and an app-level token (`xapp-…`) with `connections:write`, and invite the bot to the channel.

### Connect it through Nexus

Slack tokens live in [Nexus](nexus.md) like every other credential, never in your code or environment. JarvisCore's Slack calls go through `nexus_call` with the workspace's `slack` connection (the bot token), and the Socket Mode connection is opened by the `slack_app` atom with the app-level token:

```bash
jarviscore nexus register slack --auth-type api_key --api-key xoxb-... \
    --header-name Authorization --value-prefix "Bearer "
jarviscore nexus register slack_app --auth-type api_key --api-key xapp-... \
    --header-name Authorization --value-prefix "Bearer "
```

With a Nexus gateway, add both connections there instead. Either way, Nexus only sends each token to `slack.com`.

### Serve a room

From the terminal:

```bash
jarviscore room slack launch --channel C0123ABC --seed 10.0.0.5:7949 --capabilities approval
```

| Option | Meaning |
|---|---|
| `--channel` | The Slack channel id |
| `--people` | The name the channel's people go by on the mesh (default `team`) |
| `--capabilities` | What the channel's people do for agents, such as `approval,review`; they always have `human` |
| `--seed`, `--host`, `--port` | Join the mesh's P2P transport, so planners and agents on other nodes find the channel's people |
| `--timeout` | How long one request's work may run, in seconds (default 1800) |

This starts a node with a room agent and a HumanAgent standing for the channel's people, and serves the room until stopped. Or, in your own process with your own room agent:

```python
from jarviscore.human import HumanAgent
from jarviscore.room import Room
from jarviscore.room.slack import SlackRoom

desk = mesh.add(LaunchDesk)                                   # your RoomAgent subclass
mesh.add(HumanAgent("team", ["approval"], channel=None))
await mesh.start()

await SlackRoom(Room.for_mesh(mesh, "launch"), desk, "C0123ABC", people="team").run()
```

### Who is who

The Slack user who posts or presses a button is who the room agent acts as. That identity comes from Slack, so typing someone else's name changes nothing. By default a room member is their Slack handle. Map Slack users to the identities your organisation uses, so room roles and each person's Nexus connections line up:

```python
SlackRoom(room, desk, "C0123ABC", people="team",
          members={"U0123ABC": "alice@acme.com", "U0456DEF": "bob@acme.com"})
```

`members` can also be a function that receives the Slack user (`{"id", "name", "profile", ...}`) and returns the member.

### What it does in the channel

- A message that mentions the bot is read; a reply in one of the room's threads is read; anything else in the channel is not.
- Each request's message becomes its thread. The plan, each step, the proposal with its diff and buttons, and the agents' summary are posted there.
- Proposals show their change inline. Slack limits a message's size, so a long diff is cut short; the Full change button posts all of it.
- Work started anywhere else (the CLI, another surface, code) gets its own thread when it starts, so the channel always shows what is happening to the room.
- A question from the agents to the channel's people is posted in the thread of the work that raised it. The room agent passes on whoever answers it there.
- Where the conversation is (which thread belongs to which work, what has been posted) is saved with the room, so a restart picks up where it left off, with nothing posted twice.

## Your own surface

A surface is a class with two methods, plus an optional third:

```python
from jarviscore.room import ChatSurface


class MySurface(ChatSurface):
    key = "web:launch"        # unique per place a room is shown; keys its saved state

    async def say(self, thread, text, *, detail="", code=""):
        """Post text in a thread (None: top level). detail is quoted context, code is verbatim.
        Return the new message's id: a thread is the id of the message it hangs off."""

    async def show_proposal(self, thread, text, diff, proposal_id):
        """Post a proposal for review, ideally with an Accept button. Return its id."""

    async def history(self, thread):
        """Optional: earlier messages in a thread, as [{"person": ..., "text": ...}]."""
```

A `RoomConversation` drives it. Call `hear` for every message a person posts and `press` for every button, with the person your application authenticated:

```python
from jarviscore.room import RoomConversation, ACCEPT, SHOW_CHANGE

conversation = RoomConversation(room, desk, MySurface(), people="team")
await conversation.start()                    # introduces the room the first time
follower = asyncio.create_task(conversation.follow())   # posts progress, proposals, questions

await conversation.hear("alice@acme.com", "Can you draft the waitlist email?",
                        message_id="m1", addressed=True)
await conversation.hear("bob@acme.com", "Make it shorter", thread="m1", message_id="m2")
await conversation.press("carol@acme.com", ACCEPT, "p-221bf36b", thread="m1")
```

`addressed` says the message is for the agent (in Slack, a mention). Replies in the room's threads are read either way. In a product UI built for the room, every top-level message is usually addressed.

### Example: a room in your web app

A complete surface for a FastAPI app. The browser receives everything over a websocket and posts messages to an endpoint, with the user from your own authentication:

```python title="room_web.py"
import asyncio
from uuid import uuid4

from fastapi import Depends, FastAPI, WebSocket
from jarviscore.room import ACCEPT, ChatSurface, RoomConversation


class WebSurface(ChatSurface):
    def __init__(self, room_id):
        self.key = f"web:{room_id}"
        self.sockets = set()
        self.messages = []

    async def _post(self, message):
        message["id"] = uuid4().hex
        self.messages.append(message)
        for socket in list(self.sockets):
            await socket.send_json(message)
        return message["id"]

    async def say(self, thread, text, *, detail="", code=""):
        return await self._post({"thread": thread, "by": "agent", "text": text,
                                 "detail": detail, "code": code})

    async def show_proposal(self, thread, text, diff, proposal_id):
        return await self._post({"thread": thread, "by": "agent", "text": text,
                                 "code": diff, "proposal": proposal_id})

    async def history(self, thread):
        return [{"person": m["by"], "text": m["text"]}
                for m in self.messages if m["thread"] == thread]


app = FastAPI()
surface = WebSurface("launch")
conversation = None          # a RoomConversation(room, desk, surface, people="team"), set at startup


@app.websocket("/rooms/launch")
async def watch(socket: WebSocket):
    await socket.accept()
    surface.sockets.add(socket)
    try:
        while True:
            await socket.receive_text()
    finally:
        surface.sockets.discard(socket)


@app.post("/rooms/launch/messages")
async def post_message(body: dict, user: str = Depends(current_user)):   # your authentication
    message_id = await surface._post({"thread": body.get("thread"), "by": user, "text": body["text"]})
    asyncio.create_task(conversation.hear(user, body["text"], thread=body.get("thread"),
                                          message_id=message_id, addressed=True))
    return {"id": message_id}


@app.post("/rooms/launch/proposals/{proposal_id}/accept")
async def accept(proposal_id: str, body: dict, user: str = Depends(current_user)):
    await conversation.press(user, ACCEPT, proposal_id, body.get("thread"))
```

The same shape fits any chat product: receive its events, call `hear` and `press` with the authenticated user, and implement `say` and `show_proposal` with its API. `jarviscore.room.slack` is a complete, small example.

## Testing

`jarviscore.testing.rooms` has an in-memory `MemorySurface` and a `ScriptedRoomAgent` that runs the real room tools from a script instead of a model, so conversations are tested without a model, a chat product or a network. `jarviscore.testing.slack.FakeSlack` speaks Slack's Web API and Socket Mode protocol on a local port. Point the `slack` and `slack_app` Nexus connections at it (with a `base_url` of its address), and `SlackRoom` runs against it as it would against Slack. See [Build a Multiplayer Agent](multiplayer-agents.md#step-6-test-it-without-a-model-or-a-workspace).

## Further reading

- [Build a Multiplayer Agent](multiplayer-agents.md): a room the team talks to, from nothing to production
- [Multiplayer API](../reference/multiplayer-api.md): `RoomConversation`, `ChatSurface`, `SlackRoom` and the rest
