---
icon: material/account-group
title: "People as Peers on the Agent Mesh"
description: "Put a person on the JarvisCore mesh as a peer: discovered by capability, routed workflow steps, asked by agents, and able to ask agents back."
---

# People as Peers

A `HumanAgent` puts a person on the mesh the same way an agent is put there. It has a role and capabilities, other nodes see it in their roster, mesh planners can route steps to it, it claims workflow steps from the shared ledger, and peers reach it with `request_capability`. The difference is who does the work: each task is put in front of the person, and their answer is the result.

The person is a full peer, not only an approver. From the same terminal they can `/ask` any capability on the mesh and see who is online.

This is different from [HITL Escalation](hitl.md). HITL is an agent stopping to get a founder's sign-off on a narrow set of risky actions. A human peer is someone who owns capabilities, such as `review`, `legal`, or `pricing`, and is routed work for them like any other node.

## Join from a terminal

Start any mesh node, for example the example launch desk:

```bash
python examples/human_peer_review.py
```

Then join it as a person:

```bash
jarviscore human join alice --capabilities review --seed 127.0.0.1:7949
```

Tasks appear in the terminal as they arrive:

```text
━━ Task for you  (review · from launch_desk)  [task-cdad289372]
Review this launch post before it goes out:

JarvisCore 2.2: agents and the people they work with, on one mesh.
Answer, or /approve [note] · /reject <why> · /decline <why>.
```

| Input | Meaning |
|---|---|
| any text | The answer to the task in front of you |
| `/approve [note]` | Sign it off |
| `/reject <why>` | Refuse it. The step fails and the asker receives your reason |
| `/decline <why>` | You will not or cannot do it |
| `/ask <capability> <question>` | Ask whoever on the mesh owns that capability |
| `/peers` | List agents and people on the mesh |

Tasks that arrive while you are answering another are queued and shown in order. A task that reaches its `answer_timeout`, or whose node stops, is withdrawn from the queue. An asker that gives up waiting does not withdraw it: your answer is still recorded on your side but reaches no one.

Every person also carries the `human` capability, so a step or a peer can ask for "a person" without knowing who is online.

## Add a person in code

```python
from jarviscore import Mesh
from jarviscore.profiles import HumanAgent

mesh = Mesh(config={"p2p_enabled": True, "bind_port": 7960, "seed_nodes": "10.0.0.5:7949"})
mesh.add(HumanAgent("alice", ["review", "approve"]))
await mesh.start()
```

Or declare a standing role:

```python
class Legal(HumanAgent):
    role = "legal"
    capabilities = ["contract_review"]
    description = "The legal team. Answers within a working day."
```

`description` and `capability_descriptions` are announced to the mesh and shown to planners. By default they say the peer is a person and that answers take minutes, not seconds.

| Parameter | Default | Description |
|---|---|---|
| `name` | class `role` | Role on the mesh |
| `capabilities` | class `capabilities` | What the person can be asked for; `human` is always added |
| `channel` | `TerminalChannel()` | How tasks reach the person |
| `answer_timeout` | `3600` | Seconds before an unanswered task fails |
| `description` | "a person, not a model…" | How planners and peers see this peer |

## How work reaches a person

**Peer requests.** Any agent can ask by capability:

```python
result = await self.peers.request_capability("review", f"Approve this draft?\n\n{draft}")
if result["status"] == "success":
    answer = result["result"]["output"]   # {"response", "decision", "answered_by"}
else:
    reason = result["error"]              # e.g. "alice rejected: numbers are wrong"
```

`request_capability` waits at most 300 seconds outside a workflow; inside one, the workflow budget's `peer_timeout_seconds` sets the limit. For work that takes a person longer, route it as a workflow step, which waits for the step timeout instead.

**Workflow steps.** With Redis shared between nodes, a person's node claims pending steps for their capabilities from the ledger, like any distributed worker:

```python
results = await mesh.workflow("launch-post", [
    {"id": "draft", "agent": "writer", "task": "Write the launch post"},
    {"id": "review", "agent": "review", "task": "Approve the post", "depends_on": ["draft"]},
])
```

The person sees the task with a summary of each upstream result. A rejection fails the step with the person's reason, which reaches the workflow caller. People are never blocked by upstream uncertainty: they see the upstream results and judge for themselves.

## Results

A person's result has the usual envelope:

```python
{"status": "success", "output": {"response": "ship it", "decision": "approved", "answered_by": "alice"}}
{"status": "failure", "error": "alice rejected: too vague", "output": {...}}
```

`decision` is `answered`, `approved`, `rejected`, or `declined`. Rejected and declined tasks fail; silence past `answer_timeout` fails with `alice did not answer within 3600s`.

## Answer from files instead

`InboxChannel` writes each task to `<directory>/<role>/<task-id>.json` and waits for it to be answered. Use it for a dashboard, a chat bridge, or a person who is not at a terminal:

```bash
jarviscore human join alice --capabilities review --seed 10.0.0.5:7949 --inbox human_inbox
jarviscore human inbox
jarviscore human answer task-cdad289372 "Swap the second sentence"
jarviscore human answer task-cdad289372 --reject "The numbers are wrong"
```

A channel is any object with `async ask(item) -> HumanAnswer`; `start`, `notify`, and `stop` are optional. Notifications sent to a person (`peers.notify`) are printed in the terminal or appended to `notices.jsonl` in the inbox.

## Joining across machines

`--seed` is the `host:port` of any node already on the mesh. Set `--host` to an address the other nodes can reach. A node listens on its SWIM `--port` and on that port plus 1000 for messages, so both must be open between the machines.

!!! warning "Use a private network"
    Mesh traffic is not authenticated or encrypted. Join over a LAN or a VPN such as Tailscale, not the open internet.
