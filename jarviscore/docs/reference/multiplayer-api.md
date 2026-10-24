---
icon: material/api
title: "Multiplayer API Reference"
description: "Reference for Person, Identities, Room, RoomFeed, RoomAgent, RoomConversation, ChatSurface, SlackApp, HumanAgent and the HITL methods people's work uses."
---

# Multiplayer API

The classes behind [Multiplayer](../concepts/multiplayer.md), with their methods and what they return. For how to use them together, follow [Build a Multiplayer Agent](../guides/multiplayer-agents.md).

| Import | Classes |
|---|---|
| `jarviscore.room` | `Person`, `Account`, `Identities`, `IdentityError`, `Room`, `AskResult`, `Proposal`, `Head`, `FileChange`, `RoomFeed`, `FeedItem`, `RoomAgent`, `RoomSubAgent`, `Turn`, `RoomConversation`, `ChatSurface`, `ACCEPT`, `SHOW_CHANGE`, `RELEASE`, `DISCARD`, `CONFIRM`, `CANCEL`, `ROLES`, `VISIBILITIES`, `RoomConflict`, `RoomPermissionError` |
| `jarviscore.room.slack` | `SlackApp`, `SlackApi`, `SlackSurface`, `SlackError` |
| `jarviscore.room.work` | `resume`, `finish`, `unfinished` |
| `jarviscore.human` | `HumanAgent`, `HumanChannel`, `TerminalChannel` |
| `jarviscore.hitl` | `HITLQueue` |
| `jarviscore.testing.rooms` | `MemorySurface`, `ScriptedRoomAgent` |
| `jarviscore.testing.slack` | `FakeSlack` |

## People

| Member | |
|---|---|
| `Person(tenant, id, name="")` | A person in a tenant. `.key` is `"tenant/id"`: what credentials and audit records are keyed by. `.display` is the name others see |
| `Account(tenant, issuer, subject, name="")` | An authenticated account on a surface, such as `issuer="slack:T0123"` |
| `Identities(redis_store)` | Accounts, people, links and removals, in the mesh's Redis |
| `people.person_for(account, *, auto_provision=True)` | The person an account belongs to; a new account becomes a new person unless `auto_provision=False`. Raises `IdentityError` for removed people |
| `people.register(person)` | Record a person your application manages |
| `people.get(tenant, id)` | A person, or None if unknown or removed |
| `people.begin_link(person)` / `people.complete_link(account, code)` | A one-time code (10 minutes) that makes another account the same person |
| `people.accounts(person)`, `people.unlink(account)` | A person's accounts; let an account be someone else |
| `people.deprovision(person)` | Remove someone: their roles stop applying and their accounts are refused |
| `people.log(tenant, since=0)` | Who was added, linked, unlinked or removed, oldest first |

## Spending

`from jarviscore.auth.spending import Spending, SpendCapReached`

| Member | |
|---|---|
| `Spending(redis_store)` | Per-person ledgers and caps, in the mesh's Redis |
| `spending.set_caps(tenant, *, person="", tokens_per_day=, tokens_per_month=, usd_per_day=, usd_per_month=)` | The tenant's caps, or one person's (which override); None clears one |
| `spending.caps_for("tenant/person")`, `spending.usage("tenant/person")` | The caps that apply; tokens, USD and calls this UTC day and month |
| `spending.check("tenant/person")` | Raises `SpendCapReached` if a cap is reached |
| `SpendCapReached` | `.person`, `.period`; a model call over a cap raises it before it is made |

## Room

### Opening

| Member | |
|---|---|
| `Room.for_mesh(mesh, room_id, *, tenant)` | A room on a started mesh; it can `ask` the mesh's agents |
| `Room.open(room_id, *, tenant, redis_url=None)` | The same room without a mesh (no `ask`) |
| `await room.ensure(files=None, *, by)` | Create it with these files, owned by `by`, or return its head |
| `await room.ensure_from(snapshot, *, by)` | Create it from a captured source snapshot |
| `room.exists()`, `room.head()` | Whether it exists; its current `Head` (`version`, `updated_by`, `proposal_id`) |
| `room.id`, `room.tenant`, `room.key` | Its id, tenant, and `"tenant/id"` |

### Reading

Reading methods are for trusted code; check `room.require(person, "viewer", ...)` before reading for a person.

| Member | |
|---|---|
| `await room.read(path, version=None)` | A file's bytes, or None |
| `await room.files(version=None)`, `await room.snapshot(version=None)` | All files; the snapshot |
| `await room.diff(proposal_id)` | `FileChange`s, each with `.unified()` |
| `room.proposal(id)`, `room.proposals(status=None)` | A `Proposal`; all, or those in one status |
| `room.events(after="")`, `room.progress(workflow_id, after="")` | The room's history; a piece of work's ledger |

### Work and proposals

| Member | |
|---|---|
| `await room.ask(goal, *, asked_by, revision_of="", title="", timeout=None, plan_template=None, workflow_id="")` | Run a goal on the room as `asked_by`; returns `AskResult(workflow_id, status, proposal, summary, result, held_for, sources)` |
| `await room.propose(changes, *, by, author="", title="", base_version=None, revision_of="")` | Propose content per path (`None` deletes); None if nothing changes |
| `await room.accept(proposal_id, *, by)` | Merge it in; returns the new `Head`. Raises `RoomConflict` (with `.paths`) |
| `await room.reject(proposal_id, *, by, reason)` | Turn it down |
| `room.release(proposal_id, *, by)` | Show held work to the room (only the person it is held for) |
| `await room.checkout(directory, *, by)`, `await room.push(directory, *, by, title="")` | Work by hand |
| `room.private_sources(workflow_id)` | The connected systems a piece of work used that the room does not share |
| `room.audit(since=0, until=None)` | Records of everything done: `at`, `by`, `by_name`, `action`, `target`, `detail`, `held_for`; for work, `workflow_id`, `sources` and `usage` |
| `room.memory` | The room's team memory (`RoomMemory`) when Athena is configured; assignable |
| `room.delete(*, by)` | Delete it (owners) |

A `Proposal` has `id`, `title`, `author`, `asked_by`, `base_version`, `changes`, `paths`, `status` (`open`, `accepted`, `rejected`, `conflicted`), `revision_of`, `decided_by`, `reason`, `conflicts`, `held_for` and `sources`.

### Who can do what

| Member | |
|---|---|
| `room.role_of(person)` | `viewer`, `editor`, `owner`, or None |
| `room.can(person, role)`, `room.require(person, role, action)` | Check a role; `require` raises `RoomPermissionError` |
| `room.visible_to(person, proposal)` | Whether they may see its contents (held work is for its asker) |
| `room.members()`, `room.name_of(person_id)`, `room.settings()` | Person id to role; a name; `visibility`, `tenant_role`, `shared_connectors`, `created_by` |
| `room.set_role(person, role_or_None, *, by)` | Owners; a room keeps one owner |
| `room.set_visibility("members" \| "tenant", *, by, tenant_role="editor")` | Owners |
| `room.set_shared_connectors(providers, *, by)` | Owners: systems everyone in the room may see |

### History

| Event | Fields |
|---|---|
| `room.created` | `by`, `by_name`, `files`, `source` |
| `ask.started` | `by`, `by_name`, `goal`, `title`, `workflow_id`, `version`, `revision_of`; `follows`, `takes` for a follow-up |
| `ask.queued` | `by`, `by_name`, `workflow_id` (the running work), `queued`, `message`, `change` |
| `ask.finished`, `ask.failed` | `status` (`superseded` when another revision was accepted first), `summary`, `proposal`, `held_for`; `error` |
| `proposal.opened`, `proposal.released` | `proposal`, `author`, `title`, `paths`, `base_version`, `revision_of`, `workflow_id`, `held_for` |
| `proposal.accepted`, `proposal.rejected`, `proposal.conflicted` | `proposal`, `by`, `by_name`, `version`, `merged_over`, `line_merged`; `reason`; `paths` |
| `member.changed`, `room.visibility`, `room.connectors` | `person`, `role`; `visibility`, `tenant_role`; `shared` |

## RoomMemory

`from jarviscore.room.memory import RoomMemory`

| Member | |
|---|---|
| `RoomMemory(room, athena_client)`, `RoomMemory.from_env(room)` | A room's team memory in Athena (tenant: the room's; scope: the room; session agent `room`) |
| `await memory.said(person, text, *, thread="")`, `await memory.replied(text, *, thread="")` | Keep a public message, or the agent's public reply |
| `await memory.sync()` | Keep what the room recorded since the last sync, once per room (`RoomConversation.follow` calls it) |

## RoomFeed

| Member | |
|---|---|
| `RoomFeed(room, state=None)` | Reads the room's history and its work's progress as lines |
| `feed.poll()` | New `FeedItem`s: `text`, `kind`, `at`, `workflow_id`, `proposal`, `detail`, `held_for`, `withheld`, `cursor` |
| `feed.state()`, `feed.skip_history()` | Where it is, to resume from; start from now |

## RoomAgent

An AutoAgent with a `room` Kernel role. See [Build a Multiplayer Agent](../guides/multiplayer-agents.md#step-3-a-room-agent-people-talk-to).

| Member | |
|---|---|
| `await agent.converse(room, person, message, **turn)` | Handle one message from `person`; returns a `Turn` with `replies` and `decisions` |
| `agent.prepare(turn, action, target, reason="")` | Check and describe a decision for the person to confirm |
| `agent.running_work(room)`, `agent.stop(room, workflow_id, *, by, reason)` | Work in progress; stop it (its asker, or an owner) |
| `agent.queued_updates(room, *workflow_ids)`, `agent.recent_results(room)` | What people added to running work and no follow-up has taken yet; how the latest work ended |
| `agent.resume_work(room)` | Follow work started before this process to its end |
| `system_prompt`, `ask_options`, `subagent_class` | How it speaks; options for `room.ask`; its harness (`RoomSubAgent`) |

Its tools: `room_status`, `running_work`, `room_history`, `read_file`, `show_change`, `ask_agents`, `update_work`, `request_changes`, `propose_version`, `prepare_decision`, `answer_question`, `stay_quiet`.

Nothing anyone adds is lost while work runs. More for running work (`update_work`), or feedback on a proposal that is already being redone, is kept as `ask.queued`. When that work ends, one follow-up starts from its result with every addition made meanwhile, in the same thread. If the work was stopped, what was added to it stops with it. Each turn's brief tells the agent what is running, what is waiting to be taken up, and how recent work ended, so questions about it are answered rather than sent to the agents.

## RoomConversation and ChatSurface

| Member | |
|---|---|
| `RoomConversation(room, agent, surface, *, poll_interval=1.0, decision_seconds=600, retention_days=90, audience_seconds=30.0)` | One room's conversation on one surface |
| `await conversation.start()` | Resume saved state, unhandled messages and unfinished work |
| `await conversation.follow()` | Post updates until cancelled (one process at a time) |
| `conversation.receive(person, text, *, message_id, thread=None, addressed=False)` | Record a message once; False for a redelivery |
| `await conversation.handle(message_id)`, `await conversation.hear(...)` | Handle a received message; both at once |
| `await conversation.press(person, action, target, thread)` | A button |
| `conversation.recheck_audience()`, `conversation.can_see(person, item)` | Check who can see the surface before the next post; per-person visibility |

`ChatSurface`: `key`, `say`, `notice`, `show_proposal`, `confirm`, `audience`, `history`. See [Chat Surfaces](../guides/chat-surfaces.md#what-a-surface-implements).

## SlackApp

| Member | |
|---|---|
| `SlackApp(agent, *, tenant, api=None, identify=None, poll_interval=1.0)` | Serves a tenant's rooms in its Slack workspace |
| `slack.connect(room, channel)` | Show a room in a channel (one room per channel) |
| `await slack.start()`, `await slack.run()` | Connect; serve until cancelled |
| `await SlackApi.through_nexus(mesh=None, *, api_url=...)` | Slack's Web API and Socket Mode through the `slack` and `slack_app` Nexus connections |

`jarviscore room slack ROOM --channel ID --tenant T` runs it from the terminal. See [Chat Surfaces](../guides/chat-surfaces.md#slack).

## HumanAgent

A person or team on the mesh. See [People as Peers](../guides/human-peers.md).

| Member | |
|---|---|
| `HumanAgent(name=None, capabilities=None, *, channel=TerminalChannel(), description=None, capability_descriptions=None, answer_timeout=None, agent_id=None)` | `channel=None` leaves work in the HITL inbox |
| `agent.answer(item_id, decision, response="", by="")` | `decision`: `answered`, `approved`, `rejected` or `declined` |
| `agent.waiting()` | The person's open items |
| `answer_timeout`, `poll_interval` | Seconds before unanswered work fails (3600), and between checks for an answer (1) |

A `HumanChannel` implements any of `start(agent)`, `show(item)`, `withdraw(item_id)`, `notify(sender, message)` and `stop()`.

## HITLQueue methods for people's work

| Method | |
|---|---|
| `queue.assign(title, content, *, targets, context=None, urgency="normal")` | File work routed to a person (`input_request`): no escalation category needed |
| `queue.inbox(target=None, *, tenant=None)` | Pending items for a person or role, from every host, oldest first; only one tenant's with `tenant` |
| `queue.resolve(request_id, decision, reason="", by="")` | Answer an item, once; resumes the mesh step an escalation paused. False if it was not pending |
| `queue.expire(request_id)` | Close an unanswered item so it leaves every inbox |

Items record the mesh step that raised them (`context["mesh_workflow_id"]`, `context["mesh_step_id"]`) and the tenant of the person the work runs for (`context["tenant"]`). Escalations (`queue.request(...)`) are covered in [HITL Escalation](../guides/hitl.md).

## Testing helpers

| Helper | |
|---|---|
| `MemorySurface()` | A `ChatSurface` that keeps what is posted: `posts`, `confirmations`, `thread(id)`, `texts(id)`, `seen_by(person)`, `public()`; set `audience_problem` or `fail_next` |
| `ScriptedRoomAgent(*scripts)` | The real room tools driven by scripts, `async (tools, turn) -> reply`, one per message |
| `FakeSlack(users=..., channels=...)` | Slack's Web API and Socket Mode on a local port; people play with `say`, `click`, `join` and `leave` |
