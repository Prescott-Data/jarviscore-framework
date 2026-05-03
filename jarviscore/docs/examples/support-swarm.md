---
icon: material/lifebuoy
---

# Customer Support Swarm

[:fontawesome-brands-github: View full source](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/ex3_support_swarm.py){ .md-button }

| | |
|---|---|
| **Profile** | `CustomAgent` |
| **Infra required** | Redis + P2P (`p2p_enabled: True`) |
| **Agents** | `GatewayAgent`, `TechnicalAgent`, `BillingAgent`, `EscalationAgent` |
| **Run** | `python examples/ex3_support_swarm.py` |

---

## What it does

Four `CustomAgent` specialists form a P2P swarm. There is no central workflow orchestrator — routing is event-driven via the mailbox. A `GatewayAgent` receives inbound queries, classifies them by keyword, and routes each to the correct specialist via a mailbox message.

```
Customer query → GatewayAgent
                    ↓ classify
       ┌────────────┴────────────┐
   TechnicalAgent          BillingAgent
   (requires_auth=True)    (no auth)
   Nexus OAuth flow        Handles invoices
       │
   EscalationAgent  ← fallback for unclassified queries
   (saves to blob for human review)
```

This is also the primary end-to-end test for the **Nexus OSS auth protocol**.

---

## Key pattern: P2P mesh with auth

```python
from jarviscore import Mesh

mesh = Mesh(config={
    "redis_url": REDIS_URL,
    "p2p_enabled": True,              # (1)!
    "bind_host": "127.0.0.1",
    "bind_port": 7960,
    "node_name": "support-swarm",
    # Auth — optional, only needed for Nexus flow testing
    "auth_mode": "production",
    "nexus_gateway_url": NEXUS_GATEWAY,
})

mesh.add(GatewayAgent)
mesh.add(TechnicalAgent)   # has requires_auth=True
mesh.add(BillingAgent)
mesh.add(EscalationAgent)
await mesh.start()

# P2P agents drive themselves — use run_forever() for persistent loops
# or call agent methods directly for scripted tests (as this example does)
```

1. P2P + SWIM enabled. Without `p2p_enabled`, agents still start and communicate locally but don't use SWIM discovery across processes.

---

## Key pattern: mailbox routing

```python
class GatewayAgent(CustomAgent):
    role = "gateway"

    def _classify(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["api", "error", "bug", "auth", "401", "token"]):
            return "technical_support"
        if any(w in q for w in ["invoice", "billing", "charge", "refund"]):
            return "billing_support"
        return "escalation"

    async def route(self, query: str, customer_id: str, all_agents) -> dict:
        target_role = self._classify(query)
        target_id   = self._find_agent_id(target_role, all_agents)

        # self.mailbox is auto-injected by Mesh.start()
        self.mailbox.send(target_id, {      # (1)!
            "query": query,
            "customer_id": customer_id,
            "routed_by": self.agent_id,
        })
```

1. `self.mailbox` is auto-injected. Messages are in-process by default; switch to Redis-backed pub/sub automatically when `redis` capability is detected.

---

## Key pattern: Nexus auth injection

```python
class TechnicalAgent(CustomAgent):
    role = "technical_support"
    requires_auth = True  # (1)!

    async def handle_query(self, query: str, customer_id: str) -> str:
        if self._auth_manager:  # (2)!
            result = await self._auth_manager.make_authenticated_request(
                provider="github",
                method="GET",
                url="https://api.github.com/user",
            )
```

1. Setting `requires_auth = True` tells `Mesh.start()` to inject an `AuthenticationManager` as `self._auth_manager`.
2. On the first call, triggers the full Nexus flow: `request_connection → browser OAuth → poll ACTIVE → resolve_strategy → inject Authorization header`.

**To test the real Nexus flow**, set in `.env`:
```bash
NEXUS_GATEWAY_URL=https://your-dromos-gateway.example.com
```

Without `NEXUS_GATEWAY_URL`, the agent runs in development mode and skips auth gracefully (logs `WARNING`, not `ERROR`).

---

## Key pattern: blob escalation

Unresolved cases are written to blob storage for human review:

```python
class EscalationAgent(CustomAgent):
    async def handle_query(self, query: str, customer_id: str) -> str:
        if self._blob_storage:
            record = f"ESCALATION #{self.escalation_count}\nCustomer: {customer_id}\n..."
            await self._blob_storage.save(
                f"escalations/support-swarm/{customer_id}-{int(time.time())}.txt",
                record,
            )
```

Verify after running:
```bash
ls blob_storage/escalations/support-swarm/
```

---

## Success criteria

- [ ] 4 agents start and join the mesh
- [ ] Gateway correctly classifies and routes all 4 test queries
- [ ] `TechnicalAgent` completes Nexus auth flow (or degrades gracefully without `NEXUS_GATEWAY_URL`)
- [ ] Escalation blobs created for unclassified queries
- [ ] No `ERROR` lines in output
