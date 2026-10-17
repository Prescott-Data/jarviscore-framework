---
icon: material/google-classroom
title: "Rooms: Multiplayer Work for People and Agents"
description: "A shared, versioned workspace that a team's people and agents change together: agents propose, people review, edit by hand, accept or reject with reasons, and everyone sees it live."
---

# Rooms

A room is one shared workspace that a team's people and agents change together. It is multiplayer for the work itself, not only the chat about it: the files are the shared document, and every change, by an agent or a person, arrives as a proposal anyone in the room can see, review, accept, or reject with a reason.

- **Nobody overwrites anybody.** Each agent step works on its own copy of the room's current files. Its changes come back as a proposal; the room only moves when someone accepts one.
- **Concurrent work merges.** If the room moved since a proposal was made, accepting merges it file by file. A file both sides changed differently is a conflict that stops the accept, never a silent overwrite.
- **Rejections teach.** Rejecting with a reason and asking again hands the reason to the agents for the next attempt.
- **People work too.** People check the room out, edit in their own editor, and push, under the same rules as agents. A person routed a step in the room's work gets the files to edit for that step.
- **Everyone sees it live.** Plans, who took which step, proposals and decisions go to the room's event log.
- **The agent works as the person who asked.** Steps use the asker's own connected accounts (see [Who the agents work as](#who-the-agents-work-as)).

## Five lines for a developer

```python
from jarviscore import Mesh, Room

mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
mesh.add(Coder)                          # any agents; AutoAgent works on files out of the box
await mesh.start()

room = Room.for_mesh(mesh, "pricing")
await room.ensure({"calc.py": source}, by="alice")
asked = await room.ask("Fix the failing test in calc.py", asked_by="alice")

for change in await room.diff(asked.proposal.id):
    print(change.unified())
await room.accept(asked.proposal.id, by="bob")
```

`ask` plans the goal on the mesh, runs it on the room's current files, and returns an `AskResult` whose `proposal` holds the agents' changes, or None if they changed nothing. Goals on a room need Redis, like every `execute_goal`.

## From the terminal

```bash
jarviscore room create pricing --from ./project --as alice
jarviscore room ask pricing "Fix the failing test in calc.py" --as alice
jarviscore room watch pricing                     # live feed
jarviscore room diff pricing p-789486bf
jarviscore room reject pricing p-789486bf "Also document add()" --as bob --redo
jarviscore room accept pricing p-434beedb --as bob

jarviscore room checkout pricing ./mine           # work by hand
jarviscore room push ./mine -m "Say who owns it" --as alice --accept
```

A real session, as `watch` shows it:

```text
18:52:45  alice asked: Fix the failing test in calc.py
18:53:11  plan: step-1 (coding)
18:53:11  coder took step-1
18:54:07  ▲ p-789486bf proposed by coder for alice: Fix the failing test in calc.py (1 file, on v1)
18:54:42  ✗ bob rejected p-789486bf: Also document add()
18:54:42  bob asked: Fix the failing test in calc.py, redoing p-789486bf
18:54:48  ▲ p-81228715 proposed by alice: Say who owns it (1 file, on v1)
18:54:48  ✓ alice accepted p-81228715 → v2
18:58:01  ▲ p-434beedb proposed by coder for bob: Fix the failing test in calc.py (1 file, on v1)
18:58:19  ✓ bob accepted p-434beedb → v3, merged over 1 newer
```

Bob's redo and Alice's hand edit were made against the same version; accepting the redo merged it over her change.

Rooms are found the way a Mesh with the same settings finds them: with `REDIS_URL` (or `--redis-url`) the room lives in Redis and is shared by every node; without it, in `.jarviscore/rooms` on this machine. File contents live in the Mesh's BlobStorage. Local storage is per machine, so for people and agents on different machines use a shared backend (`STORAGE_BACKEND=azure`).

## How changes come together

| Situation | What accepting does |
|---|---|
| The room has not moved since the proposal | Applies it |
| Someone changed other files since | Merges: both sets of changes land |
| Someone changed the same file to the same content | Applies: no conflict |
| Someone changed or deleted the same file differently | Refuses with `RoomConflict`; the proposal is marked `conflicted` |

A conflicted proposal is resolved like any other: ask again on the current files, or check out, merge by hand, and push. Each accepted proposal is a new version; earlier versions stay readable (`room.read(path, version=1)`).

## People doing the work

**By hand.** `room.checkout(dir)` writes the current files to an empty directory; `room.push(dir, author=...)` proposes whatever changed there since. Pushes merge and conflict exactly like agent work.

**As part of the agents' work.** A [HumanAgent](human-peers.md) routed a step in a room's goal receives the step's files, with every earlier step's changes applied:

```text
━━ Task for you  (editing · from workflow · room-pricing-1a2b/polish)
Polish the README
  📂 /tmp/jarviscore-workspace-k3j2/workspace
     Edit the files there in your editor; your changes go in when you answer.
```

What the person changes there becomes part of the run's proposal, attributed to them alongside the agents.

**Any agent can work on files.** AutoAgent has a code sandbox. For any other agent, set `self.sandbox = WorkspaceAccess()`; its steps then find the files at `task["context"]["workspace_binding"]["path"]`.

## What a run proposes

Steps that change files plan with effect `propose`: their changes are proposals, never writes to a provider. Steps build on each other's changes, and the run's proposal holds the final state, attributed to everyone whose step changed files. The proposal's `asked_by` is the person who asked, and `revision_of` links a redo to the rejection it answers; the rejection's reason reaches the agents in `context["room"]["feedback"]`.

## Who the agents work as

Each person connects their own accounts in [Nexus](nexus.md), in their own workspace (`jarviscore nexus test github --user-id alice`). Steps of a room goal run as the person who asked: an agent calling GitHub for Alice uses Alice's connection, and the provider's own audit log shows her, not a shared bot that holds everyone's access.

The identity comes only from the goal as it was registered (`context["acting_for"]`, which `room.ask` sets from `asked_by`), never from what agents send each other, so an agent cannot borrow another person's accounts. `asked_by` itself is trusted input: set it from your own authentication (a Slack user, an SSO session), not from text a user typed. The CLI's `--as` is for a single trusted machine.

## Events

`room.events(since=seq)` returns the log; each event has `type`, `at`, `seq`, and its own fields. `jarviscore.room.feed.describe(event)` renders one line, for terminals and chat bridges.

| Type | When |
|---|---|
| `room.created` | The room was opened |
| `ask.started`, `ask.finished`, `ask.failed` | Someone asked the agents; the run ended |
| `plan.ready` | The plan's steps, with capabilities and dependencies |
| `step.claimed`, `step.completed`, `step.blocked`, ... | Who took and finished each step |
| `proposal.opened` | A change to review, with its paths, author and asker |
| `proposal.accepted`, `proposal.rejected`, `proposal.conflicted` | Decisions, with who made them and why |

## Limits

- Merging is per file: two people changing different lines of the same file conflict.
- Allowed workspace commands (`workspace_allowed_commands`) come from the configuration of the node that asks; the CLI allows none, so agents can read and edit but not run commands such as tests.
- Publishing a room to its origin, such as opening a pull request, is a separate step with its own capability.
