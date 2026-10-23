---
icon: material/folder-account
title: "Rooms: Shared Work for People and Agents"
description: "The room API: people and roles, asking agents for work, proposals and merges, work held from private access, history, the terminal and several machines."
---

# Rooms

A room is shared work that a team and its agents change together: a set of files, versioned, with every change made as a proposal that people review. This page is the room API in full. Most teams talk to a room through a [room agent](multiplayer-agents.md) instead of calling it; the room agent uses exactly these operations, as the person who spoke.

## People

Every operation on a room is done by a `Person` in the room's tenant. Where a person comes from is up to you:

```python
from jarviscore.room import Account, Identities, Person

# Your app manages its users: use your own ids.
alice = Person("acme", "u_1842", "Alice")

# Or let JarvisCore map accounts on surfaces to people.
people = Identities(mesh._redis_store)
alice = people.person_for(Account("acme", issuer="app", subject="u_1842", name="Alice"))
```

`person_for` makes an account seen for the first time a person of its own. When one human uses two surfaces, link the accounts so they are one person, with one set of roles and one set of connected accounts in Nexus. On a surface where they are already signed in, give them a one-time code; they enter it from the other surface:

```python
code = people.begin_link(alice)                          # shown to Alice in your app (10 minutes)
people.complete_link(Account("acme", "slack:T0123", "U0ALICE"), code)   # entered from Slack
```

`people.deprovision(alice)` removes someone from the tenant: every role they hold stops applying, their accounts stop resolving, and they cannot come back as a new person through the same account.

`by` and `asked_by` are trusted input. Set them from your own authentication (the user your app signed in, the Slack user who posted), never from text someone typed.

## Open a room and ask for work

```python
from jarviscore.room import Room

room = Room.for_mesh(mesh, "launch", tenant="acme")
await room.ensure({"plan.md": plan, "brief.md": brief}, by=alice)

asked = await room.ask("Fill in the Risks section of plan.md from brief.md", asked_by=alice)
asked.proposal          # the change, for people to review; None if nothing changed
asked.summary           # what the agents said they did
```

`ensure` creates the room with these files, owned by `alice`, or returns its current head if it exists. `Room.open("launch", tenant="acme")` reaches the same room from anywhere with the mesh's Redis (`REDIS_URL`), without a mesh, for everything but asking agents.

`ask` runs an ordinary goal on the room's current version, as the person who asked. Every step works in its own copy of the files, and the steps' final changes come back as one proposal. The work belongs to the mesh, not to the caller: if the calling process stops, the work goes on, and `RoomConversation` (or `jarviscore.room.work.resume`) finishes it and files its proposal, once. A `timeout` that runs out stops the work rather than leaving it running.

## Who can do what

A room is private to its members. Its creator is its owner, and owners decide who else is in it:

```python
room.set_role(bob, "editor", by=alice)
room.set_role(vic, "viewer", by=alice)
room.set_role(vic, None, by=alice)                      # remove Vic
room.set_visibility("tenant", by=alice, tenant_role="viewer")   # everyone in Acme may look
```

| Role | Can |
|---|---|
| `viewer` | read, diff, follow the room and check it out |
| `editor` | also ask the agents, propose, push, accept, reject, and answer the agents' questions |
| `owner` | also change members, who can see the room, and its shared systems |

A room always keeps at least one owner. Someone in another tenant never has a role, even with the same id. A refused action raises `RoomPermissionError` with the reason, which the room agent passes on to the person.

## Work on someone's own access

Work runs as the person who asked. Each person connects their own accounts in [Nexus](nexus.md), so an agent reading mail for Alice reads Alice's mail, limited to her access, and the provider's audit log shows her.

That raises the question of who may then see the result. Nexus records every connected system a piece of work used, and whose access it was. If the work used someone's access to a system the room does not share, its proposal is **held** for that person:

```python
asked = await room.ask("Note what changed with the venue, from my inbox", asked_by=alice)
asked.held_for                   # "u_1842": it used Alice's Gmail
asked.sources                    # [{"provider": "gmail", "person": "acme/u_1842"}]

room.visible_to(bob, asked.proposal)       # False: only Alice sees it
room.release(asked.proposal.id, by=alice)  # now everyone in the room can review it
```

Until it is released, nobody can accept it, and only Alice can discard it (`room.reject(id, by=alice, ...)`). Chat surfaces show Alice the work and show everyone else a line saying it is waiting for her.

Owners name the systems whose data everyone in the room may see, such as a team drive:

```python
room.set_shared_connectors(["google_drive"], by=alice)
```

Work that used only those, or nothing private, is shown to everyone.

## Review and decide

```python
for change in await room.diff(proposal.id):
    print(change.unified())

await room.accept(proposal.id, by=bob)
await room.reject(proposal.id, by=bob, reason="One line per risk, please")
```

To have the agents redo a proposal, ask again with `revision_of`. The agents are given the earlier attempt's files and text to start from, and what happened to it is in `context["room"]["feedback"]`. The earlier proposal does not have to be turned down first: while both are open, either can be accepted, and accepting the revision closes the one it replaces.

Only one version of a line of work (a proposal and its revisions) lands. Accepting one replaces what it revised, closes every other open version in that line ("superseded by …", including revisions of a losing version) and stops work still making one. A version built on one the team did not take cannot be accepted, even if two people accept competing versions at the same moment. A revision of work held for someone (it used their private access) is held for them too, and its text is never shown to anyone else.

Every file the agents write in the room's folder is part of the proposal, including binary files and new folders such as `output/`; the runtime's own scratch stays in `.jarviscore/`. Agents are told to put new work in a new file and to change an existing file only when the request is about it. Give the work a short `title=` to name its proposal; without one, the first sentence of the goal is used.

```python
again = await room.ask("Fill in the Risks section; one line per risk, Sam owns support",
                       asked_by=bob, revision_of=proposal.id)
```

Every decision is made once. When several people accept, reject or release the same proposal at the same moment, one of them decides and the others are told it is no longer open.

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
await room.checkout("./mine", by=alice)
# ... edit ./mine/plan.md in any editor ...
proposal = await room.push("./mine", by=alice, title="Tighter risks")
```

Pushes merge and conflict exactly like agent work. You can also propose content directly, as the room agent does when someone pastes their own version of a file:

```python
await room.propose({"email.md": new_text}, by=carol, title="Carol's version of email.md")
```

A person can also be part of the agents' work. When the planner routes a step to a [human peer](human-peers.md), they get that step's copy of the files, with the earlier steps' changes in it, and what they change there is part of the request's proposal, attributed to them alongside the agents.

## History and progress

The room keeps its history. `room.events()` returns every event in order, and `room.events(after=seq)` those after one you have seen:

| Event | When |
|---|---|
| `room.created` | The room was opened |
| `ask.started`, `ask.finished`, `ask.failed` | Someone asked for work (naming its `workflow_id`); the work ended, with its `summary` and whether it is held |
| `proposal.opened`, `proposal.released` | A change to review; a held change released to the room |
| `proposal.accepted`, `proposal.rejected`, `proposal.conflicted` | Decisions, with who made them and why |
| `member.changed`, `room.visibility`, `room.connectors` | An owner changed who is in the room, who can see it, or what it shares |

Events name people by id (`by`) and by the name others see (`by_name`).

How a piece of work is going (its plan, who took each step, what finished, what is waiting for a person) is not copied into the room. It stays in that work's own workflow ledger, which `room.progress(workflow_id)` reads. `RoomFeed` puts both together as lines people can read; it is what the terminal and chat surfaces show:

```python
from jarviscore.room import RoomFeed

feed = RoomFeed(room)
for item in feed.poll():                 # call again for what is new since
    print(item.withheld if item.held_for and item.held_for != me.id else item.text)
```

```text
Alice asked: Fill in the Risks section of plan.md from brief.md
plan: read-brief (writing) → fill-risks (editing)
writer took fill-risks
writer finished fill-risks
▲ p-6ceeb0ca proposed by writer for Alice: Fill in the Risks section of plan.md from brief.md (1 file, on v1)
the agents finished (completed) → p-6ceeb0ca to review
✗ Bob rejected p-6ceeb0ca: One line per risk, please
```

An item with `held_for` belongs to work held for that person: show them `text` and `detail`, and everyone else `withheld`.

## Memory

A room remembers what its agents keep and what its team says, shared by every agent working in it and never across rooms or tenants. What work learns from someone's own access stays private to them, and work that recalls it is held for them.

- **With [Athena](../concepts/memory.md)** (`ATHENA_URL`): the room also remembers its conversation ("Sam owns support", said once, is known a week later), on every machine.
- **Without Athena**: what agents keep goes to the local store (`.jarviscore/memory`), on one machine and in one working directory. A room worked on from several machines needs Athena.

See [Memory in a room](../concepts/memory.md#memory-in-a-room).

The room's team memory is `room.memory` (a `RoomMemory`); set it to None to keep none, or to your own to keep it elsewhere.

To erase it, an owner calls `await room.forget(by=owner)`, which removes everyone's memory in the room, including people who have left; a person erases their own with `await room.forget_person(person, by=person)`. Call these before `room.delete`. Both erase the local store and Athena, and raise unless Athena confirms.

## Spending

Work runs for whoever asked, so its model use is theirs. Every model call made while working for a person, including the room agent's own turns when they speak, is charged to them per UTC day and month, and a tenant can cap it:

```python
from jarviscore.auth.spending import Spending

spending = Spending(mesh._redis_store)
spending.set_caps("acme", tokens_per_day=2_000_000, usd_per_month=200)   # everyone in Acme
spending.set_caps("acme", person="u_1842", usd_per_month=500)           # Alice may spend more
spending.usage("acme/u_1842")       # {"day": {...tokens, usd, calls}, "month": {...}}
```

Asking for work over a cap is refused before anything starts, with when the allowance renews; the room agent tells the person so. A model call that would go over a cap during work is not made, and the work stops with the same reason rather than retrying. From the terminal: `jarviscore room caps alice --usd-per-month 500`.

## Audit

`room.audit(since=..., until=...)` returns everything done in the room as records for an auditor: when, who, what, to what, and why; for each piece of work, the connected systems it used and whose access each was, and what its model use cost. Records of private work say it was held, and for whom, never what it found.

```python
for record in room.audit(since=time.time() - 7 * 86400):
    print(record["at"], record["by_name"], record["action"], record.get("target"), record.get("detail"))
```

Who was added to the tenant, linked an account, unlinked one or was removed is in `Identities(store).log("acme")`. From the terminal: `jarviscore room audit launch --days 7 --json`.

## From the terminal

The `jarviscore room` commands are for developers and operators. They act with the access of whoever holds the Redis URL; `--as` names the person an action is recorded for and whose role is checked, and is not a login.

```bash
export REDIS_URL=redis://localhost:6379/0 JARVISCORE_TENANT=acme
jarviscore room create launch --from ./launch-docs --as alice
jarviscore room role launch bob editor --as alice
jarviscore room ask launch "Fill in the Risks section of plan.md from brief.md" --as alice
jarviscore room watch launch --as bob                 # live, until Ctrl-C
jarviscore room diff launch p-6ceeb0ca --as bob
jarviscore room reject launch p-6ceeb0ca "One line per risk, please" --as bob --redo
jarviscore room accept launch p-81228715 --as bob
jarviscore room checkout launch ./mine --as alice
jarviscore room push ./mine -m "Tighter risks" --as alice --accept
```

See the [CLI reference](../reference/cli.md#jarviscore-room) for every command.

## Teams on several machines

Point every node at the same Redis, and store files there too:

```bash
export REDIS_URL=redis://team-redis:6379/0
export STORAGE_BACKEND=redis
```

Every node then sees the same rooms, people and files. Redis holds file contents in memory, which suits documents, plans and code (single files up to 32 MB by default). For large media or datasets, use `STORAGE_BACKEND=azure`.

## Limits

- Lines merge exactly: two edits to the same line conflict even when they mean the same thing.
- Binary files are compared whole and never merged; two changes to one binary file conflict.

## Further reading

- [Build a Multiplayer Agent](multiplayer-agents.md): a room the team talks to, step by step
- [Chat Surfaces](chat-surfaces.md): a room in Slack, or in your own product
- [Multiplayer API](../reference/multiplayer-api.md): `Room`, `Identities`, `RoomFeed` and the rest in full
