---
icon: material/history
hide:
  - toc
---

# Changelog

All notable changes to JarvisCore Framework are documented here. This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

<div class="changelog-release" markdown>

## 1.0.3 <span class="changelog-date">2026-05-03</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/ekizito96" title="Muyukani Ephraim Kizito"><img src="https://github.com/ekizito96.png?size=32" alt="ekizito96"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v1.0.3" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Documentation**

- Launched the full MkDocs documentation site — Getting Started, Concepts, Guides, Reference, Examples, and Enterprise sections.
- New guides: AutoAgent, CustomAgent, Workflows, Chat, HITL, Nexus, Knowledge Base, System Prompts, Observability, FastAPI Integration, Internet Search, Migration (CrewAI + LangGraph), Testing.
- New concept pages: Architecture, Memory, Nexus, P2P, System Bundles, Agent Personas.
- New examples: Financial Pipeline, Research Network, Support Swarm, Content Pipeline, Investment Committee.

**Added**

- `mesh.run_task(agent, task, context, complexity)` — primary user-facing API for dispatching a single task to an agent by role with multi-tier model routing.
- `P2P_ENABLED=true` env var support — `Settings.p2p_enabled` is now merged into Mesh config at startup.
- `HITLCategory` enum with hard enforcement on `HITLQueue.request()` — valid categories: `auth_required`, `data_required`, `critical_action`. Invalid categories raise `ValueError`.
- Subagent hint alias map in the Planner — LLM-hallucinated hints (`analyst`, `developer`, `writer`, `scraper`) are remapped to valid roles before dispatch.
- `STEP_OUTPUT_MAX_BYTES` (default 200 KB) and `STEP_OUTPUT_PREVIEW_BYTES` (default 20 KB) — large step outputs stored as truncated preview with `_overflow` flag.
- Idempotent write guard on `RedisStore.save_step_output()` — a successful result will not be overwritten by a subsequent error payload from a stalled re-execution.
- Azure Content Filter resilience in `LLMClient` — substitution table for business phrases that trigger false-positive content rejections.
- `Kernel._get_model_for_tier()` — clean multi-tier model resolution: complexity hint → `TASK_MODEL_NANO` / `TASK_MODEL_STANDARD` / `TASK_MODEL_HEAVY` → legacy fallback.
- `MailboxManager` schema normalisation — handles both the current flat envelope schema and the pre-v1.0.2 double-nested schema transparently.

**Fixed**

- `P2P_ENABLED` env var was not forwarded to `Mesh.config`, requiring `config={"p2p_enabled": True}` explicitly even when the env var was set.
- HITL escalations could be raised for arbitrary reasons, polluting the human review queue. Now enforced at the framework level.
- Planner emitted `Unknown subagent_hint` warnings for semantically valid but aliased LLM role names.

**Changed**

- `mesh.workflow()` no longer restricted to autonomous mode — works across all mesh configurations.
- CLI references updated from `python -m jarviscore.cli.*` to the `jarviscore` entry-point CLI.

</div>

---

<div class="changelog-release" markdown>

## 1.0.2 <span class="changelog-date">2026-03-04</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v1.0.2" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Fixed**

- P2P Keepalive Spam Prevention: Added exponential backoff mechanism (45s default) to prevent continuous keepalive attempts when peers are unavailable or network has connectivity issues.
- Remote Agent Discovery Bug: Fixed `PeerClient.list_roles()` to include remote agents from SWIM mesh, not just local agents. Previously only checked local agent registry, missing agents discovered via P2P network.
- Single-Node Graceful Degradation: Added `allow_zero_peers` flag (default: True) to recognize single-node runs as valid state without triggering failure warnings.

**Changed**

- Increased `ask_peer` timeout from 600s to 7200s (2 hours) to support long-running database queries and complex analysis tasks.
- Enhanced keepalive manager with consecutive failure tracking and backoff-until timestamp for better network resilience.
- Improved keepalive logging to distinguish between expected zero-peer state and actual failures.

**Added**

- `P2P_KEEPALIVE_FAILURE_BACKOFF_SECONDS` config parameter (default: 45) for keepalive retry backoff.
- `P2P_ALLOW_ZERO_PEERS` config parameter (default: True) for single-node development and testing.

</div>

---

<div class="changelog-release" markdown>

## 1.0.1 <span class="changelog-date">2026-02-27</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v1.0.1" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Fixed**

- LICENSE link in README resolves to 404 on PyPI. Replaced relative path with absolute GitHub URL.

</div>

---

<div class="changelog-release" markdown>

## 1.0.0 <span class="changelog-date">2026-02-25</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v1.0.0" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Changed**

- Version: 0.4.0 → 1.0.0 — stable public release.
- Documentation URL updated to custom domain: `https://jarviscore.developers.prescottdata.io/`

**Added**

- Apache 2.0 license (replaces MIT); CLA/INDIVIDUAL.md, CLA/CORPORATE.md, TRADEMARK.md.
- CONTRIBUTING.md with CLA links, ruff tooling, PR checklist.
- CODE_OF_CONDUCT.md community standards.
- ENTERPRISE.md for OSS vs Enterprise comparison.
- `examples/investment_committee/` — 7-agent multi-step workflow with web dashboard (AutoAgent + CustomAgent, parallel step execution, LTM institutional memory, FastAPI dashboard on port 8004).

</div>

---

<div class="changelog-release" markdown>

## 0.4.0 <span class="changelog-date">2026-02-18</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.4.0" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

This was the largest release in JarvisCore history, introducing the complete infrastructure stack across nine phases. It added persistent storage, context distillation, telemetry, the mailbox messaging system, the function registry, the Kernel OODA loop, distributed workflow execution, Nexus authentication, and the unified memory architecture.

**Phase 1 — Foundation Layer**

`LocalBlobStorage` / `AzureBlobStorage` with `save(path, data)` / `load(path)` for any artifact. `RedisContextStore` for full Redis-backed step output, workflow graph, mailbox, HITL, and checkpoint methods. Configured via `STORAGE_BACKEND`, `STORAGE_BASE_PATH`, and `REDIS_URL`.

**Phase 2 — Context Distillation**

`Evidence`, `TruthFact`, `TruthContext`, `AgentOutput` Pydantic models. `distill_output()`, `scrub_sensitive()`, `merge_facts()` utilities. `ContextManager` for token-budget aware prompt building (priority stack: mission → plan → scratchpad → LTM → tool history → variables). `JarvisContext` enhanced with `truth`, `mailbox`, `tracer`, `human_tasks` fields.

**Phase 3 — Telemetry and Tracing**

`TraceEventType` enum covering workflow, step, kernel cognition, tool, mailbox, HITL, and context events. `TraceManager` with three output channels: Redis List (persistent), Redis PubSub (real-time), and JSONL (compliance fallback). `record_step_execution(duration, status)` Prometheus histogram and counter, enabled via `PROMETHEUS_ENABLED=true`.

**Phase 4 — MailboxManager**

`self.mailbox.send(target_id, payload)` / `read(max_messages)` for async agent messaging. Backed by Redis Streams, available in all modes when `REDIS_URL` is set.

**Phase 5 — Function Registry**

`CodeRegistry` auto-registers successfully executed code per task and promotes to `VERIFIED` on first success. Available as `agent.code_registry` in AutoAgent, persisted to `{log_dir}/function_registry/`. Includes `update_execution_stats(func_name, success, execution_time)` for graduation tracking.

**Phase 6 — Kernel / SubAgent OODA Loop**

The `Kernel` replaces AutoAgent's linear codegen → sandbox → repair pipeline with a supervised OODA loop. `ExecutionLease` enforces token/turn/wall-clock budgets per subagent role. `AgentCognitionManager` tracks budget spend per phase, detects spinning (same tool 3+ times), and enforces cognitive gates. `AdaptiveHITLPolicy` with `HumanTask` pauses execution when confidence or risk triggers fire. Fast path: simple coding tasks skip full OODA and dispatch directly to coder subagent.

**Phase 7 — Distributed WorkflowEngine**

`WorkflowEngine` persists DAG to Redis hash `workflow_graph:{wf_id}` for crash recovery. When no local agent matches a step, the engine resets status to `"pending"` and polls Redis. `Mesh._run_distributed_worker()` scans `jarviscore:active_workflows`, checks `are_dependencies_met()`, atomically claims steps via SETNX, executes, and writes output to Redis.

**Phase 7D — AuthenticationManager (Nexus)**

Set `requires_auth = True` on any agent and the Mesh injects `self._auth_manager` before `setup()`. Full NexusClient flow: `request_connection → browser OAuth → poll ACTIVE → resolve_strategy → apply headers`. Graceful degradation when `NEXUS_GATEWAY_URL` is not set.

**Phase 8 — Memory Architecture**

`UnifiedMemory(workflow_id, step_id, agent_id, redis_store, blob_storage)` with `.episodic` (EpisodicLedger via Redis Streams), `.ltm` (LongTermMemory via Redis), and `.scratch` (in-memory WorkingScratchpad). `RedisMemoryAccessor` reads step outputs across the workflow.

**Phase 9 — Mesh Integration and Auto-Injection**

Before each agent's `setup()`, the Mesh injects `_redis_store`, `_blob_storage`, and `mailbox`. Prometheus server starts automatically when `PROMETHEUS_ENABLED=true`. Agents use injected infrastructure directly with zero boilerplate.

**Production Examples**

- `ex1_financial_pipeline.py` — AutoAgent autonomous, 3-step financial analysis pipeline.
- `ex2_synthesizer.py` + `ex2_research_node1/2/3.py` — AutoAgent 4-node SWIM research cluster.
- `ex3_support_swarm.py` — CustomAgent P2P, 4-agent support routing with Nexus auth.
- `ex4_content_pipeline.py` — CustomAgent distributed, content pipeline with LTM.

**Fixed**

- `AutoAgent.execute_task`: pass `context=task.get('context')` to `sandbox.execute()` so LLM-generated code can access `previous_step_results`.

**Changed**

- P2P env var namespace: `bind_port`, `bind_host`, `seed_nodes`, `node_name` now read from `JARVISCORE_BIND_PORT`, `JARVISCORE_BIND_HOST`, `JARVISCORE_SEED_NODES`, `JARVISCORE_NODE_NAME` respectively. This isolates per-process P2P settings from the swim package's own env vars.

</div>

---

<div class="changelog-release" markdown>

## 0.3.2 <span class="changelog-date">2026-02-03</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.3.2" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Added**

Session Context Propagation: `context` parameter added to `notify()`, `request()`, `respond()`, and `broadcast()` methods. Context carries metadata like `mission_id`, `priority`, `trace_id` across message flows. `respond()` automatically propagates context from request if not overridden.

```python
response = await peers.request("analyst", {"q": "..."}, context={"mission_id": "abc"})

async def on_peer_request(self, msg):
    mission_id = msg.context.get("mission_id")
    return {"result": "..."}
```

Mesh Diagnostics: `mesh.get_diagnostics()` returns `local_node`, `known_peers`, `local_agents`, and `connectivity_status` (healthy, isolated, degraded, not_started, local_only). Includes SWIM and keepalive status when P2P is enabled.

Async Request Pattern: `ask_async(target, message, timeout, context)` returns a `request_id` immediately. `check_inbox(request_id, timeout, remove)` retrieves the response later. Enables fire-and-forget workflows where you collect results when ready.

Load Balancing Strategies: `strategy` parameter on `discover()` supports `"first"`, `"random"`, `"round_robin"`, and `"least_recent"`. `discover_one()` convenience method for single peer lookup.

MockMesh Testing Utilities: `jarviscore.testing` module with `MockPeerClient` (full mock with discovery, messaging, assertion helpers) and `MockMesh` (simplified mesh without real P2P infrastructure). Auto-injects MockPeerClient into agents during `MockMesh.start()`.

</div>

---

<div class="changelog-release" markdown>

## 0.3.1 <span class="changelog-date">2026-02-02</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.3.1" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Breaking Changes**

ListenerAgent has been merged into CustomAgent. Migration requires only an import change:

```python
# Before
from jarviscore.profiles import ListenerAgent

# After
from jarviscore.profiles import CustomAgent
```

All handler methods work exactly the same way. No other code changes required.

**Changed**

CustomAgent now includes P2P handlers: `on_peer_request(msg)`, `on_peer_notify(msg)`, `on_error(error, msg)`, and the built-in `run()` listener loop. The profile architecture was simplified from three profiles (AutoAgent + CustomAgent + ListenerAgent) to two (AutoAgent + CustomAgent), removing the "which profile do I use?" confusion.

</div>

---

<div class="changelog-release" markdown>

## 0.3.0 <span class="changelog-date">2026-01-29</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.3.0" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Added**

ListenerAgent Profile: New `ListenerAgent` class for handler-based P2P communication with `on_peer_request(msg)` and `on_peer_notify(msg)` handlers. No more manual `run()` loops required for simple P2P agents.

FastAPI Integration: `JarvisLifespan` context manager reduces FastAPI integration from approximately 100 lines to 3. Automatic agent lifecycle management with support for both `p2p` and `distributed` modes.

Cognitive Discovery: `peers.get_cognitive_context()` generates LLM-ready peer descriptions with dynamic peer awareness. Auto-updates when peers join or leave the mesh.

Cloud Deployment: `agent.join_mesh(seed_nodes)` for self-registration without central orchestrator. `agent.leave_mesh()` for graceful departure. `agent.serve_forever()` for container deployments. `RemoteAgentProxy` for automatic cross-node agent visibility.

</div>

---

<div class="changelog-release" markdown>

## 0.2.1 <span class="changelog-date">2026-01-23</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.2.1" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Fixed**

- P2P message routing stability improvements.
- Workflow engine dependency resolution edge cases.

</div>

---

<div class="changelog-release" markdown>

## 0.2.0 <span class="changelog-date">2026-01-15</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.2.0" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Added**

CustomAgent profile for integrating existing agent code. P2P mode for direct agent-to-agent communication. Distributed mode combining workflow engine with P2P. `@jarvis_agent` decorator for wrapping existing classes. `wrap()` function for wrapping existing instances. `JarvisContext` for workflow context access. Peer tools: `ask_peer`, `broadcast`, `list_peers`.

**Changed**

Mesh now supports three modes: `autonomous`, `p2p`, `distributed`. Agent base class now includes P2P support.

</div>

---

<div class="changelog-release" markdown>

## 0.1.0 <span class="changelog-date">2026-01-01</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.1.0" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Added**

Initial release. AutoAgent profile with LLM-powered code generation. Workflow engine with dependency management. Sandbox execution (local and remote). Auto-repair for failed code. Internet search integration (DuckDuckGo). Multi-provider LLM support (Claude, OpenAI, Azure, Gemini). Result storage and code registry.

</div>
