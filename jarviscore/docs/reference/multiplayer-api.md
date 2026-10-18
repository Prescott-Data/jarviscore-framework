---
icon: material/api
title: "Multiplayer API Reference"
description: "Reference for JarvisCore's multiplayer classes: Room, RoomFeed, RoomAgent, RoomConversation, ChatSurface, SlackRoom, HumanAgent and the HITL methods people's work uses."
---

# Multiplayer API

The classes behind [Multiplayer](../concepts/multiplayer.md), with their methods and what they return. For how to use them together, follow [Build a Multiplayer Agent](../guides/multiplayer-agents.md).

| Import | Classes |
|---|---|
| `jarviscore.room` | `Room`, `AskResult`, `Proposal`, `Head`, `FileChange`, `RoomFeed`, `FeedItem`, `RoomAgent`, `RoomSubAgent`, `Turn`, `RoomConversation`, `ChatSurface`, `ACCEPT`, `SHOW_CHANGE`, `RoomConflict`, `RoomPermissionError` |
| `jarviscore.room.slack` | `SlackRoom`, `SlackApi`, `SlackError` |
| `jarviscore.human` | `HumanAgent`, `HumanChannel`, `TerminalChannel` |
| `jarviscore.hitl` | `HITLQueue` |
| `jarviscore.testing.rooms` | `MemorySurface`, `ScriptedRoomAgent` |
| `jarviscore.testing.slack` | `FakeSlack` |

## Room

A versioned set of files a team and its agents change together. See [Rooms](../guides/rooms.md).

### Opening

| Method | Returns | |
|---|---|---|
| `Room.for_mesh(mesh, room_id)` | `Room` | The room on a started Mesh, using its Redis and file storage; `ask` runs on that mesh |
| `Room.open(room_id, *, redis_url=None, settings=None)` | `Room` | The room as any process sharing the mesh's Redis (`REDIS_URL`) and storage sees it |
| `await room.ensure(files=None, *, by="")` | `Head` | Create the room with `{path: text or bytes}` at version 1, or return the existing head |
| `await room.ensure_from(snapshot, *, by="")` | `Head` | Create the room from a captured source snapshot, such as a repository |

### Reading

| Method | Returns |
|---|---|
| `room.head()` | `Head(version, snapshot_id, manifest_blob_path, updated_by, updated_at, proposal_id)` |
| `await room.files(version=None)` | `{path: bytes}` at a version (default: current) |
| `await room.read(path, version=None)` | The file's bytes, or `None` |
| `await room.snapshot(version=None)` | The version's `SourceSnapshot` |

### Work and proposals

| Method | Returns | |
|---|---|---|
| `await room.ask(goal, *, asked_by, revision_of="", timeout=None, plan_template=None, workflow_id="")` | `AskResult` | Run `goal` on the current files as `asked_by`; a room on `for_mesh` only |
| `await room.propose(changes, *, author, title="", asked_by="", base_version=None, workflow_id="", revision_of="")` | `Proposal` or `None` | Propose `{path: content or None}`; `None` deletes a file. `None` if nothing changes |
| `await room.push(directory, *, author, title="", asked_by="")` | `Proposal` or `None` | Propose what changed in a checkout |
| `await room.checkout(destination)` | `Head` | Copy the current files into an empty directory |
| `await room.diff(proposal_id)` | `[FileChange]` | Each has `path`, `status` (`added`, `modified`, `deleted`), `before`, `after`, and `unified()` |
| `await room.accept(proposal_id, *, by)` | `Head` | Merge it into the room; raises `RoomConflict` (with `.paths`) when changes clash |
| `await room.reject(proposal_id, *, by, reason)` | `Proposal` | Turn it down |
| `room.proposal(proposal_id)`, `room.proposals(status=None)` | `Proposal`, `[Proposal]` | By id; all, or those `open`, `accepted`, `rejected` or `conflicted` |

`AskResult` has `workflow_id`, `status`, `proposal` (or `None`), `summary` and `result` (the goal's full result).

`Proposal` has `id`, `title`, `author`, `asked_by`, `base_version`, `changes`, `status`, `workflow_id`, `revision_of`, `decided_by`, `decided_at`, `reason`, `accepted_version` and `conflicts`.

### Who can do what

| Method | |
|---|---|
| `room.set_role(person, role, *, by)` | `role` is `viewer`, `editor`, `owner`, or `None` to remove; owners only, and the first role makes an open room members-only |
| `room.members()` | `{person: role}`; empty for an open room |
| `room.role_of(person)`, `room.can(person, role)` | The person's role, or whether it reaches `role` |
| `room.require(person, role, action)` | Raises `RoomPermissionError` with a readable reason when they can't |

### History

| Method | Returns |
|---|---|
| `room.events(after="")` | The room's events after event id `after`, oldest first; each has `type`, `at`, `seq` and its own fields |
| `room.progress(workflow_id, after="")` | That work's workflow ledger: `dag_published`, `step_claimed` (with `role`), `step_completed`, `step_blocked`, and so on |
| `room.note(kind, **fields)` | Record an event of your own; returns its id |

| Event | Fields |
|---|---|
| `room.created` | `by`, `files` |
| `ask.started` | `by`, `goal`, `workflow_id`, `version`, `revision_of` |
| `ask.finished` | `by`, `workflow_id`, `status`, `summary`, `proposal` |
| `ask.failed` | `by`, `workflow_id`, `error` |
| `proposal.opened` | `proposal`, `by`, `asked_by`, `title`, `base_version`, `paths`, `revision_of`, `workflow_id` |
| `proposal.accepted` | `proposal`, `by`, `author`, `asked_by`, `version`, `paths`, `merged_over`, `line_merged` |
| `proposal.rejected` | `proposal`, `by`, `author`, `reason` |
| `proposal.conflicted` | `proposal`, `by`, `paths`, `version` |
| `member.changed` | `by`, `person`, `role` |

## RoomFeed

Reads a room's history and the progress of each piece of work as lines people can read. Nothing is stored.

| Method | |
|---|---|
| `RoomFeed(room, state=None)` | Start from the beginning, or from a saved `state` |
| `feed.poll()` | `[FeedItem]` new since the last poll |
| `feed.skip_history()` | Start from now |
| `feed.state()` | Where it is, to save and resume from |

`FeedItem` has `text`, `kind` (the event type, or `progress`), `at`, `workflow_id`, `proposal`, `detail` (such as the agents' summary) and `event` (the raw event or ledger entry).

## RoomAgent

The agent a team talks to about a room's work: an `AutoAgent` with the Kernel role `room`. See [Build a Multiplayer Agent](../guides/multiplayer-agents.md#step-4-a-room-agent-people-talk-to).

| Member | |
|---|---|
| `await agent.converse(room, person, message, **turn)` | Handle one message from `person` (who it acts as; from your authentication). Returns the `Turn`, whose `replies` holds what to post. Work it starts continues afterwards |
| `system_prompt` | Leads the room role's instructions: your team, its people, its conventions |
| `subagent_class` | The role's harness, `RoomSubAgent` by default; subclass it to add tools |
| `ask_options` | Passed to `Room.ask` for the work it starts, such as `{"timeout": 1800}` |
| `mesh_worker = False` | Planners never route steps to it and it claims none; people reach it through a surface |

`Turn` fields you can pass to `converse`: `thread`, `proposal` (the thread's proposal), `addressed`, `history` (`[{"person", "text"}]`), `questions` (open HITL items for the people there), `on_work(workflow_id)`, `on_proposal(proposal_id)`. `RoomConversation` fills them in.

The `room` role's tools: `room_status`, `room_history`, `read_file`, `show_change`, `ask_agents`, `request_changes`, `accept`, `reject`, `propose_version`, `answer_question` and `stay_quiet`. None of them takes the acting person as a parameter: it is always the person who spoke.

## RoomConversation and ChatSurface

`RoomConversation` connects a room and its agent to one surface. See [Chat Surfaces](../guides/chat-surfaces.md).

| Method | |
|---|---|
| `RoomConversation(room, agent, surface, *, people=None, poll_interval=1.0)` | `people` is the role of the HumanAgent standing for the people on this surface; its questions are posted here |
| `await conversation.start()` | Load where this surface left off; introduce the room the first time |
| `await conversation.follow()` | Post progress, proposals and the agents' questions until cancelled |
| `await conversation.hear(person, text, *, thread=None, message_id="", addressed=False)` | A message from `person`. Read when `addressed` or posted in one of the room's threads |
| `await conversation.press(person, action, proposal_id, thread)` | A button: `ACCEPT` or `SHOW_CHANGE` |
| `conversation.threads()` | The surface's thread ids this conversation owns |

A `ChatSurface` implements `say(thread, text, *, detail="", code="") -> id` and `show_proposal(thread, text, diff, proposal_id) -> id`, optionally `history(thread)`, and sets a unique `key`.

## SlackRoom and SlackApi

| Member | |
|---|---|
| `SlackRoom(room, agent, channel, *, people=None, members=None, api=None, poll_interval=1.0)` | A room in a Slack channel. `members`: `{slack_user_id: member}` or a function of the Slack user |
| `await slack_room.run()` | Connect and serve until cancelled (`start()` connects only) |
| `await SlackApi.through_nexus(mesh=None)` | Slack calls through Nexus: the `slack` connection signs Web API calls, `slack_app` opens Socket Mode |

`jarviscore room slack ROOM --channel ID` runs both. See [Chat Surfaces](../guides/chat-surfaces.md#slack).

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
| `queue.inbox(target=None)` | Pending items for a person or role, from every agent, oldest first |
| `queue.resolve(request_id, decision, reason="", by="")` | Answer an item; `reason` comes back as the resolution's `note` |
| `queue.expire(request_id)` | Close an unanswered item so it leaves every inbox |

Escalations (`queue.request(...)`) are covered in [HITL Escalation](../guides/hitl.md).

## Testing helpers

| Helper | |
|---|---|
| `MemorySurface()` | A `ChatSurface` that keeps what is posted: `posts`, `thread(id)`, `texts(id)` |
| `ScriptedRoomAgent(*scripts)` | The real room tools driven by scripts, `async (tools, turn) -> reply`, one per message |
| `FakeSlack(users=...)` | Slack's Web API and Socket Mode on a local port; people play with `say` and `click` |
