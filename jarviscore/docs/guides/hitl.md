---
icon: material/account-supervisor
---

# Human-in-the-Loop (HITL) Escalation

JarvisCore agents are designed to operate autonomously. The Human-in-the-Loop (HITL) system exists for the narrow set of situations where a human decision is genuinely required — not for quality checks or uncertainty the agent should resolve itself.

This guide covers when to escalate, the complete `HITLQueue` API, how resolutions are delivered back to the agent, and how to wire up a review dashboard.

---

## When to Escalate (and When Not To)

The HITL system enforces a strict **category gate**. Every escalation request must declare one of three permitted categories. Passing any other category raises `ValueError` at call time, forcing the agent to reconsider before the item reaches a human reviewer.

| Category | When to use |
|---|---|
| `auth_required` | A Nexus credential is missing, expired, or has insufficient scope. The agent cannot proceed without a human supplying or re-authorising a credential. |
| `data_required` | A piece of data that only a human can supply is missing (e.g., a founder's personal bank details, an unpublished contract, internal pricing). |
| `critical_action` | The next action is irreversible or high-consequence (e.g., sending a bulk email campaign, triggering a payment, deploying to production). |

**Do not escalate for:**

- Output quality doubts ("the summary seemed too short")
- Self-validation ("is this analysis correct?")
- General uncertainty where the agent can take a safe fallback action
- Routine content review

Agents must handle those cases autonomously. The HITL queue is for the founder's inbox, not for the agent's confidence management.

---

## Accessing the Queue

`self.hitl` is injected into every agent by the Mesh at `start()` time. You do not instantiate `HITLQueue` directly.

```python
class MyAgent(AutoAgent):
    async def execute_task(self, task: str, context: dict = None) -> dict:
        # The hitl attribute is always available
        item_id = self.hitl.request(
            title="Approve investor deck before sending",
            content="The deck is ready for Q2 investor distribution. Approve to proceed.",
            urgency="high",
            category="critical_action",
            context={"file": "output/q2_deck.pdf", "recipients": 47},
        )
        ...
```

---

## HITLQueue API

### request

Submits a new review item to the human inbox. Returns a `request_id` string you use to poll for the decision.

```python
item_id = self.hitl.request(
    title="GitHub OAuth token expired for user 'alice'",
    content="The researcher agent attempted to read private repos for user 'alice' "
            "but the OAuth token has expired. Re-authorise via the Nexus dashboard.",
    urgency="high",
    category="auth_required",
    context={
        "workflow_id": context.get("workflow_id"),
        "step_id": "fetch_repos",
        "provider": "github",
        "user_id": "alice",
    },
)
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | `str` | Yes | Headline shown in the review list. Never truncated — keep it descriptive. |
| `content` | `str` | Yes | Full details for the reviewer. Markdown is supported. Truncated to 2,000 characters. |
| `urgency` | `str` | No | One of `"low"`, `"normal"`, `"high"`, `"critical"`. Default: `"normal"`. |
| `category` | `str` | Yes | One of `"auth_required"`, `"data_required"`, `"critical_action"`. Any other value raises `ValueError`. |
| `context` | `dict` | No | Structured metadata. String values are truncated to 1,000 characters. |

Raises `ValueError` if `urgency` or `category` is invalid.

---

### check

Non-blocking poll. Returns `HITLResolution` if the item has been decided, `None` if still pending.

```python
resolution = self.hitl.check(item_id)
if resolution is not None:
    if resolution.is_approved:
        await self._proceed()
    else:
        logger.warning("Action rejected: %s", resolution.reason)
```

The resolution is checked against the flat JSON file first (always available), then against Redis if configured.

---

### wait

Async-polling version of `check`. Suspends the calling coroutine until a decision arrives or the timeout expires. The event loop remains active during the wait.

```python
try:
    resolution = await self.hitl.wait(item_id, timeout=3600, poll_interval=10)
    if resolution.is_approved:
        await self._send_email_campaign()
    else:
        return {"status": "cancelled", "reason": resolution.reason}
except TimeoutError:
    return {"status": "timeout", "message": "No decision received within 1 hour."}
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `request_id` | `str` | Required | ID returned from `request()` |
| `timeout` | `float` | `3600.0` | Maximum seconds to wait before raising `TimeoutError` |
| `poll_interval` | `float` | `10.0` | Seconds between each check |

---

### pending

Returns all pending HITL items submitted by the calling agent. Useful before submitting a new request to avoid duplicates.

```python
pending = self.hitl.pending()
already_waiting = any(p["title"].startswith("GitHub OAuth") for p in pending)
if not already_waiting:
    self.hitl.request(...)
```

---

### resolve

Programmatically resolves a HITL item. Intended for testing and auto-approval logic. In production, items are resolved by human reviewers writing to the JSON file or the Redis store.

```python
# In a test
self.hitl.resolve(item_id, decision="approved", reason="Test auto-approval")
```

| Parameter | Type | Description |
|---|---|---|
| `request_id` | `str` | ID of the item to resolve |
| `decision` | `str` | `"approved"` or `"rejected"` |
| `reason` | `str` | Optional explanation stored on the resolution |

---

## Full Pattern: Request-Wait-Branch

The standard HITL pattern for a `CustomAgent`:

```python title="agents/campaign_sender.py"
from jarviscore import CustomAgent

class CampaignSenderAgent(CustomAgent):
    name = "Campaign Sender"
    role = "campaign-sender"

    async def on_peer_request(self, msg) -> dict:
        context = msg.data.get("context", {})
        campaign = await self.prepare_campaign(msg.data.get("task", ""))

        # 1. Escalate — declare the irreversible action
        item_id = self.hitl.request(
            title=f"Approve email campaign: {campaign['name']}",
            content=(
                f"**Recipients:** {campaign['recipient_count']:,}\n"
                f"**Subject:** {campaign['subject']}\n\n"
                f"**Preview:**\n{campaign['body_preview']}"
            ),
            urgency="high",
            category="critical_action",
            context={
                "workflow_id": context.get("workflow_id"),
                "campaign_id": campaign["id"],
            },
        )

        self._logger.info("Awaiting approval for campaign %s", campaign["id"])

        # 2. Wait (up to 24 hours)
        try:
            resolution = await self.hitl.wait(item_id, timeout=86400)
        except TimeoutError:
            return {"status": "timeout", "campaign_id": campaign["id"]}

        # 3. Branch on decision
        if resolution.is_approved:
            await self.send_campaign(campaign)
            return {"status": "sent", "campaign_id": campaign["id"]}
        else:
            return {
                "status": "cancelled",
                "campaign_id": campaign["id"],
                "reason": resolution.reason,
            }
```

---

## Review Persistence

The `HITLQueue` uses dual persistence.

**File store (always active):** Every `request()` call writes a JSON file to the `hitl_inbox/` directory in the project root. Any dashboard or script can poll this directory to display pending items.

```
hitl_inbox/
  hitl-20260501-143022-a1b2c3d4.json
  hitl-20260501-150047-e5f6a7b8.json
```

**Redis store (when configured):** If Redis is connected, the item is also persisted via `RedisContextStore.create_hitl_request_typed()`. Redis-backed dashboards can receive real-time push notifications instead of polling.

A resolution written to either store is detected by `check()` and `wait()` automatically.

---

## Resolving Items from a Dashboard

To resolve an item from a custom dashboard, update the JSON file:

```python
import json
from pathlib import Path

def resolve_item(request_id: str, decision: str, reason: str = ""):
    filepath = Path("hitl_inbox") / f"{request_id}.json"
    data = json.loads(filepath.read_text())
    data["status"] = decision        # "approved" or "rejected"
    data["decision"] = decision
    data["decision_reason"] = reason
    data["decided_at"] = "2026-05-01T15:30:00"
    filepath.write_text(json.dumps(data, indent=2))
```

The agent's `wait()` loop detects the status change on its next poll cycle.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `HITL_ENABLED` | `false` | Enable automatic Kernel escalation when confidence is below threshold |
| `HITL_MAX_CONFIDENCE` | `0.8` | Confidence threshold below which the Kernel escalates to HITL |

When `HITL_ENABLED=true`, the Kernel escalates automatically. When `HITL_ENABLED=false` (the default), HITL is still available to agents via `self.hitl.request()` — only the automatic Kernel escalation is disabled.

For testing HITL flows in unit tests without a running agent, see [Testing Agents — HITL flows](testing.md#testing-hitl-flows).
