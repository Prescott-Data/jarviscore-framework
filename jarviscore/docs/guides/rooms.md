---
icon: material/google-classroom
title: "Rooms: Shared Work for People and Agents"
description: "A room is a versioned set of files a team and its agents change together: agents propose, people review and decide, concurrent work merges, and every decision is kept with who made it and why."
---

# Rooms

A room is the shared work in a multiplayer system: a set of files a team and its agents change together. It can hold a launch plan, a brief, a contract draft, website copy, a pricing sheet, a dataset or code. Nothing in it is specific to software.

Three rules make it safe for many people and agents at once:

- **Nobody overwrites anybody.** Every change, by an agent or a person, arrives as a proposal. The room only moves when someone accepts one.
- **Concurrent work merges.** Accepting a proposal made against an older version merges it over the newer work. Edits to different files, or to different lines of one document, both land. Only edits to the same lines that differ are a conflict, and a conflict stops the accept instead of overwriting anyone.
- **Everything is on the record.** Every request, proposal and decision is kept with the person who made it and their reason.

This guide covers the room itself. For how rooms fit with people, the room agent and chat, read [Multiplayer](../concepts/multiplayer.md) and [Build a Multiplayer Agent](multiplayer-agents.md).

## Open a room and ask for work

Rooms live in the mesh's Redis, like the goals that work on them. On a started mesh:

```python
from jarviscore.room import Room

room = Room.for_mesh(mesh, "launch")
await room.ensure({"plan.md": plan, "brief.md": brief}, by="alice")

asked = await room.ask("Fill in the Risks section of plan.md from brief.md", asked_by="alice")
print(asked.status, asked.summary)
```

`ensure` creates the room with these files at version 1, or returns the existing room unchanged. `ask` runs the request as a [goal](goal-execution.md) on the room's current version: the planner makes the steps, your agents claim them, and every step works on its own copy of the files with the changes of the steps before it applied. It returns an `AskResult` whose `proposal` holds the final changes, or `None` if the work changed nothing (a question, for example; its answer is in `summary`). Pass `timeout=` to bound how long the work may take.

Any agent can do the work. An AutoAgent's Kernel gives whichever sub-agent does the step the tools to read, search and edit the files. A CustomAgent finds them at `task["context"]["workspace_binding"]["path"]`. Which commands agents may run on them (`pytest`, `make`, a linter) is decided by the node that runs the step, through `workspace_allowed_commands` in its Mesh config.

`Room.open("launch")` reaches the same room from anywhere that shares the mesh's Redis (`REDIS_URL`) and file storage, without a mesh: for a script, a dashboard or the CLI.

## Review and decide

```python
proposal = asked.proposal
for change in await room.diff(proposal.id):
    print(change.unified())                     # a unified diff per file

await room.accept(proposal.id, by="bob")                                  # the room moves to v2
await room.reject(proposal.id, by="bob", reason="One line per risk, please")
```

A rejection's reason is for whoever tries again. Asking with `revision_of` passes it to the agents, and links the new proposal to the one it answers:

```python
again = await room.ask("Fill in the Risks section of plan.md from brief.md",
                       asked_by="bob", revision_of=proposal.id)
```

The agents receive the earlier attempt and the reason in the step's task and in `context["room"]["feedback"]`. Accepting a revision closes the proposal it replaces.

## How changes come together

| Since the proposal was made, someone... | Accepting it |
|---|---|
| changed nothing | Applies it |
| changed other files | Merges: both sets of changes land |
| changed other lines of the same text file | Merges the lines: both edits land |
| made the same change | Applies it: there is nothing to conflict |
| changed the same lines differently, or deleted a file it changes | Raises `RoomConflict` and marks the proposal `conflicted` |

The same rule combines agents working in parallel in one request: two agents writing different sections of one document both land.

A conflicted proposal is resolved like any other piece of work: ask again with `revision_of` (the agents are told which files changed in the meantime), or check the files out, merge by hand and push. Every accepted proposal is a new version, and earlier versions stay readable: `await room.read("plan.md", version=1)`.

## Working by hand

People don't have to go through agents. `checkout` copies the current files into an empty directory, and `push` proposes whatever changed there since:

```python
await room.checkout("./mine")
# ... edit ./mine/plan.md in any editor ...
proposal = await room.push("./mine", author="alice", title="Tighter risks")
```

Pushes merge and conflict exactly like agent work. You can also propose content directly, as the room agent does when someone pastes their own version of a file:

```python
await room.propose({"email.md": new_text}, author="carol", title="Carol's version of email.md")
```

A person can also be part of the agents' work. When the planner routes a step to a [human peer](human-peers.md), they get that step's copy of the files, with the earlier steps' changes in it, and what they change there is part of the request's proposal, attributed to them alongside the agents.

## Who the work runs as

Each person connects their own accounts in [Nexus](nexus.md), in their own workspace (`jarviscore nexus test github --user-id alice`). The steps of a request run as the person who asked: an agent calling GitHub for Alice uses Alice's connection, limited to what Alice can access, and GitHub's audit log shows her, not a shared bot holding everyone's access.

That identity comes only from the goal as it was registered (`room.ask` sets `context["acting_for"]` from `asked_by`), never from what agents send each other, so no agent can borrow another person's accounts. `asked_by` and `by` are trusted input: set them from your own authentication (the Slack user who posted, your application's signed-in user), never from text someone typed. The CLI's `--as` is for a single trusted machine.

## Who can do what

A room is open by default: everyone can ask, propose, accept and reject, and everyone sees everything. Its creator can make it members-only by giving someone a role:

```python
room.set_role("bob", "editor", by="alice")      # alice created it, and becomes its owner
room.set_role("vic", "viewer", by="alice")
room.members()                                  # {"alice": "owner", "bob": "editor", "vic": "viewer"}
```

| Role | Can |
|---|---|
| `viewer` | read, diff, follow the room |
| `editor` | also ask the agents, propose, push, accept and reject |
| `owner` | also change members |

A room always keeps at least one owner. A refused action raises `RoomPermissionError` with the reason, and the room agent passes that reason on to the person.

## History and progress

The room keeps its history for good. `room.events()` returns every event in order, and `room.events(after=seq)` returns those after one you have seen:

| Event | When |
|---|---|
| `room.created` | The room was opened |
| `ask.started`, `ask.finished`, `ask.failed` | Someone asked for work, which names its `workflow_id`; the work ended, with its `summary` |
| `proposal.opened` | A change to review, with its files, author and asker |
| `proposal.accepted`, `proposal.rejected`, `proposal.conflicted` | Decisions, with who made them and why |
| `member.changed` | Someone's role was set or removed |

How a piece of work is going (its plan, who took each step, what finished or is blocked) is not copied into the room. It stays in that work's own workflow ledger, and `room.progress(workflow_id)` reads it. `RoomFeed` puts both together as lines people can read, which is what the CLI and chat surfaces show:

```python
from jarviscore.room import RoomFeed

feed = RoomFeed(room)
for item in feed.poll():                 # call again for what is new since
    print(item.text)
```

```text
alice asked: Fill in the Risks section of plan.md from brief.md
plan: read-brief (writing) → fill-risks (editing)
writer took fill-risks
writer finished fill-risks
▲ p-6ceeb0ca proposed by writer for alice: Fill in the Risks section of plan.md from brief.md (1 file, on v1)
the agents finished (completed) → p-6ceeb0ca to review
✗ bob rejected p-6ceeb0ca: One line per risk, please
```

## From the terminal

Everything above works from the terminal, with `REDIS_URL` pointing at the mesh's Redis:

```bash
jarviscore room create launch --from ./launch-docs --as alice
jarviscore room ask launch "Fill in the Risks section of plan.md from brief.md" --as alice
jarviscore room watch launch                      # live, until Ctrl-C
jarviscore room diff launch p-6ceeb0ca
jarviscore room reject launch p-6ceeb0ca "One line per risk, please" --as bob --redo
jarviscore room accept launch p-81228715 --as bob
jarviscore room checkout launch ./mine
jarviscore room push ./mine -m "Tighter risks" --as alice --accept
```

See the [CLI reference](../reference/cli.md#jarviscore-room) for every command.

## Teams on several machines

Point every node and every person's CLI at the same Redis, and store files there too:

```bash
export REDIS_URL=redis://team-redis:6379/0
export STORAGE_BACKEND=redis
```

Every node then sees the same rooms and the same files. Redis holds file contents in memory, which suits documents, plans and code (single files up to 32 MB by default). For large media or datasets, use `STORAGE_BACKEND=azure`.

## Limits

- Lines merge exactly: two edits to the same line conflict even when they mean the same thing.
- A room's files are text or binary, compared whole. Binary files are never merged; two changes to one binary file conflict.

## Further reading

- [Build a Multiplayer Agent](multiplayer-agents.md): a room the team talks to, step by step
- [Chat Surfaces](chat-surfaces.md): a room in Slack, or in your own product
- [Multiplayer API](../reference/multiplayer-api.md): `Room`, `RoomFeed` and the rest in full
