---
icon: material/account-multiple-outline
title: "People as Peers on the Mesh"
description: "Put people on the mesh with HumanAgent: planners route steps to them, agents ask them, and they answer from a terminal, the CLI, a dashboard or a room's chat."
---

# People as Peers

Some work belongs to a person: a review, a sign-off, a decision only someone accountable can make, or a judgement no model should make alone. A `HumanAgent` puts a person, or a team, on the mesh as a peer with capabilities, such as `review`, `legal-review` or `approval`. Planners route steps to them like to any other node, agents ask them by capability, and they appear in every node's roster.

What differs is who does the work. Each piece of work for a person becomes an item in JarvisCore's HITL store, addressed to them. It waits there, through restarts, until someone answers it: in a terminal, with `jarviscore human answer`, from a review dashboard, or in the thread of a [room's chat](chat-surfaces.md). The answer is the step's result.

This is different from [HITL escalation](hitl.md). Escalation is an agent pausing for a person's sign-off on one risky action. A human peer owns part of the work and is planned for from the start.

## Add a person

```python
from jarviscore import Mesh
from jarviscore.human import HumanAgent

mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
mesh.add(HumanAgent("alice", ["review", "approve"]))
await mesh.start()
```

Or declare a standing role for a team:

```python
class Legal(HumanAgent):
    role = "legal"
    capabilities = ["contract-review"]
    description = "The legal team. Answers within a working day."
```

Every HumanAgent also has the capability `human`, so a step or a peer can ask for "a person" without knowing who is around. `description` and `capability_descriptions` are what planners and peers see. By default they say this peer is a person and that answers take minutes, not seconds, so planners use people for what needs them.

| Parameter | Default | What it does |
|---|---|---|
| `name` | the class `role` | The person's role on the mesh |
| `capabilities` | the class `capabilities` | What they can be asked for; `human` is always added |
| `channel` | `TerminalChannel()` | Where their work is shown; `None` leaves it in the HITL inbox |
| `answer_timeout` | `3600` | Seconds before unanswered work fails |
| `description` | "a person, not a model…" | How planners and peers see this peer |

## How work reaches a person

Work arrives three ways, and all three end the same way:

- **A workflow step.** The planner routes a step with one of the person's capabilities to them, and their node claims it from the shared ledger.
- **A peer request.** An agent asks for a capability with `peers.request_capability("review", "Is the draft ready?")`.
- **A step in a room's work.** The same as a workflow step, with the room's files to work on (see below).

In each case the HumanAgent files an item in the HITL store with `HITLQueue.assign`: what is asked, what came before it (earlier steps' results), and who it is for. It shows the item on the person's channel and waits for an answer.

## How a person answers

**In a terminal.** `TerminalChannel` shows each item as it arrives. The person types their answer, then picks how to send it:

```text
━━ Work for you  (review · for writer · wf-launch/review-post)
Is the launch post ready to publish?

draft:
Orbit launches Wednesday ...
Type your answer and press Enter.
> Cut the second paragraph, the rest is good
  Send it as: 1 answer · 2 approval · 3 rejection · 4 decline  [1]
> 3
  ✓ sent as rejected
```

**From anywhere else.** With `channel=None` (or `jarviscore human join --no-terminal`), items wait in the HITL inbox and anything can answer them: a script, your dashboard, or a colleague's terminal.

```bash
jarviscore human inbox alice
jarviscore human answer hitl-20261018-153012-1a2b3c4d "Looks good, ship it" --approve
jarviscore human answer hitl-20261018-153012-1a2b3c4d --reject "The price is wrong"
```

In code, `agent.waiting()` lists a person's open items and `agent.answer(item_id, decision, response)` answers one. A review surface can also use the HITL store directly: `HITLQueue.inbox("alice")` and `HITLQueue.resolve(...)`.

**In a room's chat.** When a step of a room's work is routed to a HumanAgent, its question is asked in the thread of that work, in the room's chat, and the first of the room's editors to answer there, in their own words, answers it. Questions are shown only in the room whose work raised them, in its tenant. See [Chat Surfaces](chat-surfaces.md).

## What an answer means

| Decision | Meaning | The step |
|---|---|---|
| `answered` | They did the work or gave the answer | Succeeds; the response is the result |
| `approved` | They signed it off | Succeeds |
| `rejected` | They refused it | Fails, with their reason |
| `declined` | They will not or cannot do it | Fails, with their reason |

The step's output is `{"response": ..., "decision": ..., "answered_by": ...}`. When no one answers within `answer_timeout`, the step fails with "alice did not answer within 3600s", and the item is withdrawn from the person's channel.

## Work on files

When a person's step is part of work on a [room](rooms.md) or another workspace, they get that step's copy of the files, with every earlier step's changes applied. The item shows where the files are:

```text
━━ Work for you  (editing · for bob · room-launch-1a2b3c4d/polish)
Polish the announcement email
  📂 /tmp/jarviscore-workspace-k3j2/workspace
     Edit the files there in your editor; your changes go in when you answer.
```

What they change there before answering becomes part of the work's proposal, attributed to them alongside the agents.

## Join from a terminal

A person can join a mesh with no code:

```bash
jarviscore human join alice --capabilities review,approve --seed 10.0.0.5:7949
```

This starts a node whose only agent is a HumanAgent for Alice, with her work shown in the terminal. Add `--no-terminal` to leave it in the HITL inbox instead, or `--redis-url` to claim workflow steps from the shared ledger.

## Joining across machines

`--seed` is the `host:port` of any node already on the mesh. Set `--host` to an address the other nodes can reach. A node listens on its SWIM `--port` and on that port plus 1000 for messages, so both must be open between the machines.

!!! warning "Use a private network"
    Mesh traffic is not authenticated or encrypted. Join over a LAN or a VPN such as Tailscale, not the open internet.

## Write your own channel

A channel decides where a person sees their work: a mobile push, an email, a ticket. Subclass `HumanChannel`. Each new item is passed to `show`, and the person's answer goes back through the agent:

```python
from jarviscore.human import HumanChannel


class EmailChannel(HumanChannel):
    async def show(self, item):
        await send_email(to=self.agent.role, subject=item["title"], body=item["content"],
                         reply_link=f"https://review.acme.com/items/{item['id']}")


# Later, when the person answers from your page:
alice.answer(item_id, "approved", "Looks right")
```

`start`, `withdraw`, `notify` and `stop` are optional. The item stays in the HITL store until it is answered, so a channel can be lost or restarted without losing work.

## Further reading

- [HITL Escalation](hitl.md): an agent pausing for a person's sign-off
- [Rooms](rooms.md): people and agents changing shared work together
- [Chat Surfaces](chat-surfaces.md): people answering in a room's chat
