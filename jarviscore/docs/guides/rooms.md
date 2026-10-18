---
icon: material/google-classroom
title: "Rooms: Multiplayer Work for People and Agents"
description: "A shared, versioned workspace that a team's people and agents change together: agents propose, people review, edit by hand, accept or reject with reasons, and everyone sees it live."
---

# Rooms

A room is one shared workspace that a team's people and agents change together. It is multiplayer for the work itself, not only the chat about it: the files are the shared documents, and every change, by an agent or a person, arrives as a proposal anyone in the room can see, review, accept, or reject with a reason.

A room holds any work that lives in files: a launch plan, a brief, a contract draft, website copy, a pricing sheet, a dataset, or code. Nothing in it is specific to software.

- **Nobody overwrites anybody.** Each agent step works on its own copy of the room's current files. Its changes come back as a proposal; the room only moves when someone accepts one.
- **Concurrent work merges.** If the room moved since a proposal was made, accepting merges it. Edits to different lines of the same document both land; only edits to the same lines that differ are a conflict, which stops the accept rather than silently overwriting anyone.
- **Rejections teach.** Rejecting with a reason and asking again hands the reason to the agents for the next attempt.
- **People work too.** People check the room out, edit in their own editor, and push, under the same rules as agents. A person routed a step in the room's work gets the files to edit for that step.
- **Everyone sees it live.** Plans, who took which step, proposals and decisions go to the room's event log.
- **The agent works as the person who asked.** Steps use the asker's own connected accounts (see [Who the agents work as](#who-the-agents-work-as)).

## Five lines for a developer

```python
from jarviscore import Mesh, Room

mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
mesh.add(Writer)                         # AutoAgent or CustomAgent: both get the room's files
await mesh.start()

room = Room.for_mesh(mesh, "launch")
await room.ensure({"plan.md": plan, "brief.md": brief}, by="alice")
asked = await room.ask("Fill in the Goals and Risks of plan.md from brief.md", asked_by="alice")

for change in await room.diff(asked.proposal.id):
    print(change.unified())
await room.accept(asked.proposal.id, by="bob")
```

A CustomAgent needs no extra code: its step finds the room's files at `task["context"]["workspace_binding"]["path"]`, and whatever it changes there is its work.

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

## People and agents on different machines

Set two variables everywhere: the team's Redis, and Redis as the file store.

```bash
export REDIS_URL=redis://team-redis:6379/0
export STORAGE_BACKEND=redis
```

That is all a team needs: every person's CLI and every agent node then sees the same rooms and the same files. Redis holds file contents in memory, so it suits documents, plans, code and modest data (single files up to 32 MB by default); for large media or datasets use `STORAGE_BACKEND=azure`. Without `REDIS_URL`, rooms live on one machine in `.jarviscore/rooms`.

## How changes come together

| Situation | What accepting does |
|---|---|
| The room has not moved since the proposal | Applies it |
| Someone changed other files since | Merges: both sets of changes land |
| Someone changed other lines of the same text file | Merges the lines: both edits land |
| Someone made the same change | Applies: no conflict |
| Someone changed the same lines differently, or deleted a file the proposal changed | Refuses with `RoomConflict`; the proposal is marked `conflicted` |

The same rule combines agents working in parallel: two agents writing different sections of one document in the same run both land.

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

**Any agent works on files.** AutoAgent opens and edits them with its workspace tools, whatever the task (writing, analysis, code); a step that should change files but only answers in text is asked once to put the work in the files. A CustomAgent finds them at `task["context"]["workspace_binding"]["path"]`. An agent with its own sandbox keeps it.

**Commands.** Which commands agents may run on the files (`pytest`, `make`, a linter) is decided by the node that runs them: set `workspace_allowed_commands` in that node's Mesh config.

## What a run proposes

Steps that change files plan with effect `propose`: their changes are proposals, never writes to a provider. Steps build on each other's changes, and the run's proposal holds the final state, attributed to everyone whose step changed files. The proposal's `asked_by` is the person who asked, and `revision_of` links a redo to the rejection it answers; the rejection's reason reaches the agents in `context["room"]["feedback"]`.

## Who the agents work as

Each person connects their own accounts in [Nexus](nexus.md), in their own workspace (`jarviscore nexus test github --user-id alice`). Steps of a room goal run as the person who asked: an agent calling GitHub for Alice uses Alice's connection, and the provider's own audit log shows her, not a shared bot that holds everyone's access.

The identity comes only from the goal as it was registered (`context["acting_for"]`, which `room.ask` sets from `asked_by`), never from what agents send each other, so an agent cannot borrow another person's accounts. `asked_by` itself is trusted input: set it from your own authentication (a Slack user, an SSO session), not from text a user typed. The CLI's `--as` is for a single trusted machine.

## Who can do what

A room is open by default: everyone on the team can ask, propose, accept and reject, and sees everything. Its creator can make it members-only:

```bash
jarviscore room role launch bob editor --as alice
jarviscore room role launch vic viewer --as alice
jarviscore room members launch
```

| Role | Can |
|---|---|
| `viewer` | read, watch, diff |
| `editor` | also ask the agents, push, accept, reject |
| `owner` | also change members |

The creator becomes an owner when the first member is added, and a room always keeps at least one owner. In code: `room.set_role(person, role, by=...)`, `room.members()`, `room.can(person, "editor")`. A refused action raises `RoomPermissionError`.

## Events

`room.events(since=seq)` returns the log; each event has `type`, `at`, `seq`, and its own fields. `jarviscore.room.feed.describe(event)` renders one line, for terminals and chat bridges.

| Type | When |
|---|---|
| `room.created` | The room was opened |
| `ask.started`, `ask.finished`, `ask.failed` | Someone asked the agents; the run ended |
| `plan.ready` | The plan's steps, with capabilities and dependencies |
| `step.claimed`, `step.completed`, `step.blocked`, ... | Who took and finished each step |
| `proposal.opened` | A change to review, with its paths, author and asker |
| `proposal.accepted`, `proposal.rejected`, `proposal.conflicted` | Decisions, with who made them and why; `line_merged` lists files combined line by line |
| `member.changed` | Someone's role was set or removed |

## Limits

- Lines are merged exactly: two edits to the same line conflict even if they are compatible in meaning.
- Who someone is comes from your application (`asked_by`, `by`) or the CLI's `--as`; connect a chat surface or SSO for real identities.
