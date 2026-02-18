"""
Example 3 — Real-Time Customer Support Swarm
=============================================
Profile  : CustomAgent
Mode     : P2P (SWIM discovery + ZMQ messaging, no workflow engine)
Auth     : Production mode — tests the REAL Nexus protocol end-to-end

What this example proves
------------------------
This is the primary test of the deployed Dromos / Nexus gateway. Running it
exercises the full NexusClient protocol stack:

  1. NexusClient.request_connection(provider, user_id, scopes)
     → POST /v1/request-connection  →  (connection_id, auth_url)

  2. CLIFlowHandler.present_auth_url(auth_url, provider)
     → Opens browser (or prints URL) so user can complete OAuth consent

  3. CLIFlowHandler.wait_for_completion()  ← polls every 2s (configurable)
     → NexusClient.check_connection_status(connection_id)
     → GET /v1/check-connection/{connection_id}
     → Blocks until status == "ACTIVE"

  4. LifecycleMonitor.monitor_connection(connection_id)
     → Starts background health-tracking for the active connection

  5. NexusClient.resolve_strategy(connection_id)
     → GET /v1/token/{connection_id}
     → Returns DynamicStrategy (type: oauth2 | api_key | basic_auth)

  6. NexusClient.apply_strategy_to_request(strategy, method, url)
     → Injects Authorization header into the outbound HTTP call

Prerequisites
-------------
    # Set in .env (or export before running):
    NEXUS_GATEWAY_URL=https://your-dromos-gateway.example.com
    REDIS_URL=redis://localhost:6379/0
    CLAUDE_API_KEY=sk-ant-...          # only needed if using LLM responses

    docker compose -f docker-compose.infra.yml up -d   # Redis
    pip install -e ".[redis,prometheus]"
    python examples/ex3_support_swarm.py

Agents
------
  GatewayAgent     — routes queries to specialist via mailbox
  TechnicalAgent   — requires_auth=True → gets _auth_manager (Nexus flow)
  BillingAgent     — no auth (verify _auth_manager is None)
  EscalationAgent  — no auth; handles unresolved cases

Phases exercised
----------------
Phase 2  : SWIM P2P (all 4 agents discover each other)
Phase 4  : MailboxManager — GatewayAgent routes queries via mailbox.send()
Phase 7D : AuthenticationManager(mode="production") injected into TechnicalAgent;
           full NexusClient request_connection → poll → resolve flow tested
Phase 8  : UnifiedMemory per agent; EpisodicLedger records every interaction
Phase 9  : Auto-injected redis + blob + mailbox before each agent's setup()
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import CustomAgent
from jarviscore.memory import UnifiedMemory

REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379/0")
NEXUS_GATEWAY    = os.getenv("NEXUS_GATEWAY_URL", "")
WORKFLOW_SESSION = "support-swarm"


# ═══════════════════════════════════════════════════════════════════════════════
# TECHNICAL AGENT — requires Nexus auth to call external APIs
# ═══════════════════════════════════════════════════════════════════════════════

class TechnicalAgent(CustomAgent):
    """
    Handles technical queries: API errors, integration bugs, auth issues.

    requires_auth = True  →  Phase 7D: Mesh injects self._auth_manager
    On first authenticated call the full Nexus flow runs:
      request_connection → browser OAuth → poll ACTIVE → resolve_strategy → apply headers
    """
    role = "technical_support"
    capabilities = ["technical", "debugging", "api_help", "integration"]
    requires_auth = True   # ← triggers _auth_manager injection (Phase 7D)

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.memory = None
        self._auth_manager = None   # set by Mesh.start() if requires_auth=True

    async def setup(self):
        await super().setup()
        # Phase 9: self._redis_store and self._blob_storage already injected
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_SESSION,
            step_id=self.agent_id,
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        auth_status = "✓ injected" if self._auth_manager else "✗ not injected"
        self._logger.info(f"[{self.role}] _auth_manager: {auth_status}")

    async def handle_query(self, query: str, customer_id: str) -> str:
        """
        Resolve a technical query.
        If auth is available, makes an authenticated API call via Nexus.
        """
        # Phase 8: log the incoming query to episodic ledger
        if self.memory and self.memory.episodic:
            await self.memory.episodic.append({
                "event": "query_received",
                "agent": self.role,
                "customer_id": customer_id,
                "query": query[:200],
                "ts": time.time(),
            })

        # Phase 7D: Nexus protocol — request_connection → poll → resolve_strategy
        if self._auth_manager:
            print(f"\n  [TechnicalAgent] Auth manager available — initiating Nexus flow...")
            print(f"  [TechnicalAgent] Provider: github  |  User: support-swarm")
            try:
                # This triggers the FULL Nexus flow:
                # 1. request_connection → auth_url from Dromos gateway
                # 2. CLIFlowHandler opens browser / prints URL
                # 3. User completes OAuth in browser
                # 4. poll check_connection_status until ACTIVE
                # 5. LifecycleMonitor starts tracking the connection
                # 6. resolve_strategy → DynamicStrategy
                # 7. apply_strategy_to_request → Authorization header injected
                result = await self._auth_manager.make_authenticated_request(
                    provider="github",
                    method="GET",
                    url="https://api.github.com/user",
                )
                auth_note = f"[Nexus OK — HTTP {result.get('status_code', '?')}]"
                print(f"  [TechnicalAgent] Nexus auth complete: {auth_note}")
            except Exception as exc:
                auth_note = f"[Nexus auth failed: {exc}]"
                print(f"  [TechnicalAgent] {auth_note}")
        else:
            auth_note = "[no auth manager — development mode]"

        resolution = (
            f"Technical support response for: '{query}'\n"
            f"Auth: {auth_note}\n"
            f"Resolution: Investigated the API error. The issue appears to be an "
            f"authentication token expiry. Please regenerate your API key in the dashboard."
        )

        # Phase 8: log resolution to episodic ledger
        if self.memory and self.memory.episodic:
            await self.memory.episodic.append({
                "event": "query_resolved",
                "agent": self.role,
                "customer_id": customer_id,
                "resolution_length": len(resolution),
                "ts": time.time(),
            })

        return resolution

    async def execute_task(self, task: dict) -> dict:
        query = task.get("task", task.get("query", "No query provided"))
        customer_id = task.get("customer_id", "anon")
        resolution = await self.handle_query(query, customer_id)
        return {"status": "success", "output": resolution}


# ═══════════════════════════════════════════════════════════════════════════════
# BILLING AGENT — no auth (verify _auth_manager is None)
# ═══════════════════════════════════════════════════════════════════════════════

class BillingAgent(CustomAgent):
    """
    Handles billing queries: invoices, subscriptions, refunds.
    No requires_auth — verifies _auth_manager stays None.
    """
    role = "billing_support"
    capabilities = ["billing", "invoices", "subscriptions", "refunds"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.memory = None

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_SESSION,
            step_id=self.agent_id,
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        # Verify: no auth manager injected (no requires_auth=True)
        has_auth = hasattr(self, "_auth_manager") and self._auth_manager is not None
        self._logger.info(f"[{self.role}] _auth_manager: {'set ✗ unexpected' if has_auth else 'None ✓ correct'}")

    async def handle_query(self, query: str, customer_id: str) -> str:
        if self.memory and self.memory.episodic:
            await self.memory.episodic.append({
                "event": "billing_query",
                "customer_id": customer_id,
                "query": query[:200],
                "ts": time.time(),
            })

        return (
            f"Billing support response for: '{query}'\n"
            f"Resolution: Your invoice has been located. A refund of $49.99 will be "
            f"processed within 5-7 business days to your original payment method."
        )

    async def execute_task(self, task: dict) -> dict:
        query = task.get("task", task.get("query", "No query"))
        customer_id = task.get("customer_id", "anon")
        resolution = await self.handle_query(query, customer_id)
        return {"status": "success", "output": resolution}


# ═══════════════════════════════════════════════════════════════════════════════
# ESCALATION AGENT — handles unresolved cases
# ═══════════════════════════════════════════════════════════════════════════════

class EscalationAgent(CustomAgent):
    """
    Handles cases that cannot be resolved by technical or billing support.
    Stores unresolved queries in blob for human review.
    """
    role = "escalation"
    capabilities = ["escalation", "complex_issues", "human_handoff"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.memory = None
        self.escalation_count = 0

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_SESSION,
            step_id=self.agent_id,
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )

    async def handle_query(self, query: str, customer_id: str) -> str:
        self.escalation_count += 1

        # Phase 1: save escalation record to blob for human review
        if self._blob_storage:
            record = (
                f"ESCALATION #{self.escalation_count}\n"
                f"Customer: {customer_id}\n"
                f"Query: {query}\n"
                f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
            )
            blob_path = f"escalations/{WORKFLOW_SESSION}/{customer_id}-{int(time.time())}.txt"
            await self._blob_storage.save(blob_path, record)

        if self.memory and self.memory.episodic:
            await self.memory.episodic.append({
                "event": "escalation",
                "customer_id": customer_id,
                "escalation_num": self.escalation_count,
                "ts": time.time(),
            })

        return (
            f"Case escalated to senior support team.\n"
            f"Case #{self.escalation_count} opened for: '{query[:80]}'\n"
            f"A specialist will contact {customer_id} within 2 hours."
        )

    async def execute_task(self, task: dict) -> dict:
        query = task.get("task", task.get("query", "No query"))
        customer_id = task.get("customer_id", "anon")
        resolution = await self.handle_query(query, customer_id)
        return {"status": "success", "output": resolution}


# ═══════════════════════════════════════════════════════════════════════════════
# GATEWAY AGENT — routes queries via mailbox
# ═══════════════════════════════════════════════════════════════════════════════

class GatewayAgent(CustomAgent):
    """
    Receives support queries and routes them to the correct specialist
    via Phase-4 MailboxManager.

    Routing rules (keyword-based):
      - "api", "error", "bug", "auth", "integration"  → technical_support
      - "invoice", "billing", "charge", "refund"       → billing_support
      - anything else                                  → escalation
    """
    role = "gateway"
    capabilities = ["routing", "intake", "triage"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.routed = 0

    def _classify(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["api", "error", "bug", "auth", "integration", "401", "403", "token"]):
            return "technical_support"
        if any(w in q for w in ["invoice", "billing", "charge", "refund", "subscription", "payment"]):
            return "billing_support"
        return "escalation"

    def _find_agent_id(self, role: str, all_agents) -> str:
        """Find agent_id by role from the mesh agent list."""
        for ag in all_agents:
            if ag.role == role:
                return ag.agent_id
        return role   # fallback to role name

    async def route(self, query: str, customer_id: str, all_agents) -> dict:
        """Route a query to the appropriate specialist."""
        target_role = self._classify(query)
        target_id   = self._find_agent_id(target_role, all_agents)
        self.routed += 1

        icon = {"technical_support": "🔧", "billing_support": "💳", "escalation": "⚠️"}.get(target_role, "→")
        print(f"  [Gateway] {icon}  Routing to '{target_role}' | query: {query[:60]}...")

        # Phase 4: send via MailboxManager
        if self.mailbox:
            self.mailbox.send(target_id, {
                "query": query,
                "customer_id": customer_id,
                "routed_by": self.agent_id,
            })
            print(f"  [Gateway] Mailbox message sent to {target_id}")

        return {"routed_to": target_role, "target_id": target_id}

    async def execute_task(self, task: dict) -> dict:
        return {"status": "success", "output": "Gateway active — use route() for query routing"}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "=" * 70)
    print("JarvisCore — Example 3: Customer Support Swarm")
    print("CustomAgent | P2P Mode | Production Auth (Real Nexus Gateway)")
    print("=" * 70)

    # Validate Nexus gateway URL
    if not NEXUS_GATEWAY:
        print("\n[WARNING] NEXUS_GATEWAY_URL not set.")
        print("  TechnicalAgent will have auth_mode='production' configured but")
        print("  AuthenticationManager will raise ValueError on first auth call.")
        print("  Set NEXUS_GATEWAY_URL in .env to test the full Nexus flow.\n")

    print(f"\n[Config] NEXUS_GATEWAY_URL = {NEXUS_GATEWAY or '(not set)'}")
    print(f"[Config] REDIS_URL         = {REDIS_URL}")

    # ── Mesh setup ────────────────────────────────────────────────────────────
    mesh = Mesh(
        mode="p2p",
        config={
            "redis_url": REDIS_URL,
            "bind_host": "127.0.0.1",
            "bind_port": 7960,
            "node_name": "support-swarm",
            # Phase 7D: activate AuthenticationManager with real Nexus gateway
            "auth_mode": "production",
            "nexus_gateway_url": NEXUS_GATEWAY,
            "nexus_default_user_id": "support-swarm-agent",
            "auth_open_browser": True,   # open browser for OAuth consent
        },
    )

    gateway     = mesh.add(GatewayAgent)
    technical   = mesh.add(TechnicalAgent)
    billing     = mesh.add(BillingAgent)
    escalation  = mesh.add(EscalationAgent)

    all_agents = [gateway, technical, billing, escalation]

    try:
        await mesh.start()

        # ── Phase 9 verification ──────────────────────────────────────────────
        print("\n[Phase 9] Infrastructure injection:")
        for ag in all_agents:
            print(f"  {ag.role:20s} | redis={'✓' if ag._redis_store else '✗'}  "
                  f"blob={'✓' if ag._blob_storage else '✗'}  "
                  f"mailbox={'✓' if ag.mailbox else '✗'}")

        # ── Phase 7D verification ─────────────────────────────────────────────
        print("\n[Phase 7D] Auth manager injection (requires_auth=True only):")
        print(f"  TechnicalAgent._auth_manager : {'✓ injected' if technical._auth_manager else '✗ None'}")
        print(f"  BillingAgent._auth_manager   : {'✗ unexpected' if getattr(billing, '_auth_manager', None) else '✓ None (correct)'}")
        print(f"  EscalationAgent._auth_manager: {'✗ unexpected' if getattr(escalation, '_auth_manager', None) else '✓ None (correct)'}")

        # ── P2P verification ──────────────────────────────────────────────────
        print("\n[Phase 2] P2P mesh started | Agents:", [ag.role for ag in all_agents])

        # Wait for SWIM to stabilise
        await asyncio.sleep(1)

        # ── Test queries ──────────────────────────────────────────────────────
        test_queries = [
            ("My API keeps returning 401 Unauthorized errors",     "cust-001"),
            ("I was charged twice for my subscription last month",  "cust-002"),
            ("The dashboard shows wrong data for my organisation",  "cust-003"),
            ("API token refresh is failing with integration error", "cust-004"),
        ]

        print("\n" + "─" * 70)
        print("TEST QUERIES (routing + Nexus auth flow)")
        print("─" * 70)

        for query, customer_id in test_queries:
            print(f"\n[Customer {customer_id}] {query}")

            # Gateway routes the query
            route_result = await gateway.route(query, customer_id, all_agents)
            target_role = route_result["routed_to"]
            target_id   = route_result["target_id"]

            # Find the target agent and call execute_task directly
            agent_map = {ag.agent_id: ag for ag in all_agents}
            target_agent = agent_map.get(target_id)

            if target_agent:
                task_result = await target_agent.execute_task({
                    "task": query,
                    "customer_id": customer_id,
                })
                print(f"  [Response] {task_result.get('output', '')[:200]}")
            else:
                print(f"  [Warning] Agent {target_id} not found in this process")

            await asyncio.sleep(0.5)

        # ── Phase 4: Read mailbox messages ────────────────────────────────────
        print("\n[Phase 4] Mailbox check (messages routed by Gateway):")
        for ag in [technical, billing, escalation]:
            if ag.mailbox:
                messages = ag.mailbox.read(max_messages=10)
                print(f"  {ag.role}: {len(messages)} mailbox message(s)")
                for msg in messages:
                    print(f"    → from {msg.get('sender', '?')}: {str(msg.get('message', ''))[:80]}")

        # ── Phase 8: EpisodicLedger check ─────────────────────────────────────
        print("\n[Phase 8] EpisodicLedger entries:")
        for ag in [technical, billing, escalation]:
            if ag.memory and ag.memory.episodic:
                entries = await ag.memory.episodic.tail(count=3)
                print(f"  {ag.role}: {len(entries)} recent entries")

        # ── Phase 1: Blob escalation records ──────────────────────────────────
        print(f"\n[Phase 1] Blob escalation records:")
        print(f"  ls blob_storage/escalations/{WORKFLOW_SESSION}/")

        # ── Summary ───────────────────────────────────────────────────────────
        print(f"\n{'=' * 70}")
        print(f"Support Swarm Summary")
        print(f"  Queries routed  : {gateway.routed}")
        print(f"  Escalations     : {escalation.escalation_count}")
        print(f"  Nexus auth flow : {'tested ✓' if technical._auth_manager else 'skipped (no NEXUS_GATEWAY_URL)'}")
        print(f"\nVerify Nexus session:")
        print(f"  redis-cli xrange ledgers:{WORKFLOW_SESSION} - +")
        print(f"  ls blob_storage/escalations/{WORKFLOW_SESSION}/")
        print(f"{'=' * 70}\n")

    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        import traceback
        traceback.print_exc()

    finally:
        await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
