# Changelog

All notable changes to JarvisCore Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.0] - 2026-02-18

### Added — Infrastructure Stack (Phases 1–9)

#### Phase 1 — Foundation Layer
- `LocalBlobStorage` / `AzureBlobStorage`: `save(path, data)` / `load(path)` for any artifact
- `RedisContextStore`: full Redis-backed step output, workflow graph, mailbox, HITL, checkpoint methods
- `STORAGE_BACKEND=local|azure`, `STORAGE_BASE_PATH`, `REDIS_URL` configuration

#### Phase 2 — Context Distillation
- `Evidence`, `TruthFact`, `TruthContext`, `AgentOutput` Pydantic models (`context/truth.py`)
- `distill_output()`, `scrub_sensitive()`, `merge_facts()` utilities (`context/distillation.py`)
- `ContextManager`: token-budget aware prompt builder (priority stack: mission → plan → scratchpad → LTM → tool history → variables)
- `JarvisContext` enhanced with `truth`, `mailbox`, `tracer`, `human_tasks` fields

#### Phase 3 — Telemetry / Tracing
- `TraceEventType` enum: workflow, step, kernel cognition, tool, mailbox, HITL, context events (`telemetry/events.py`)
- `TraceManager`: three output channels — Redis List (persistent), Redis PubSub (real-time), JSONL (compliance fallback) (`telemetry/tracer.py`)
- `record_step_execution(duration, status)` — Prometheus histogram + counter; enable via `PROMETHEUS_ENABLED=true`

#### Phase 4 — MailboxManager
- `self.mailbox.send(target_id, payload)` / `read(max_messages)` for async agent messaging
- Redis Streams backed; available in all modes when `REDIS_URL` is set

#### Phase 5 — Function Registry
- `CodeRegistry`: auto-registers successfully executed code per task; promotes to `VERIFIED` on first success
- Available as `agent.code_registry` in AutoAgent; persisted to `{log_dir}/function_registry/`
- `update_execution_stats(func_name, success, execution_time)` for graduation tracking

#### Phase 6 — Kernel / SubAgent OODA Loop
- `Kernel`: replaces AutoAgent's linear codegen→sandbox→repair pipeline with a supervised OODA loop
- `ExecutionLease`: token/turn/wall-clock budgets per subagent role (`kernel/lease.py`)
  - Role profiles: `coder` (coding model, 240k tokens), `researcher`, `communicator` (task model)
- `AgentCognitionManager`: tracks budget spend per phase (DISCOVERY→ANALYSIS→IMPLEMENTATION→COMPLETION), detects spinning (same tool 3+ times), enforces cognitive gate (`kernel/cognition.py`)
- `BaseSubAgent` + text tool-call protocol (`THOUGHT/TOOL/PARAMS → DONE/RESULT`) (`kernel/subagent.py`)
- `AdaptiveHITLPolicy` + `HumanTask`: pauses execution for human approval/input when confidence/risk triggers fire (`kernel/hitl.py`)
- Fast path: simple coding tasks skip full OODA, dispatch directly to coder subagent

#### Phase 7 — Distributed WorkflowEngine
- WorkflowEngine persists DAG to Redis hash `workflow_graph:{wf_id}` for crash recovery
- When no local agent matches a step, engine resets status → `"pending"` and polls Redis
- `Mesh._run_distributed_worker()`: background asyncio task scans `jarviscore:active_workflows`,
  checks `are_dependencies_met()`, atomically claims steps via SETNX, executes, writes output to Redis
- `redis_store.register_active_workflow()`, `get_active_workflows()`, `get_all_step_ids()` added

#### Phase 7D — AuthenticationManager (Nexus)
- Set `requires_auth = True` on any agent; Mesh injects `self._auth_manager` before `setup()`
- Full NexusClient flow: `request_connection → browser OAuth → poll ACTIVE → resolve_strategy → apply headers`
- Config: `auth_mode="production"`, `nexus_gateway_url`, `nexus_default_user_id`
- Graceful degradation: `_auth_manager = None` when `NEXUS_GATEWAY_URL` not set

#### Phase 8 — Memory Architecture
- `UnifiedMemory(workflow_id, step_id, agent_id, redis_store, blob_storage)`
- `.episodic` — `EpisodicLedger`: Redis Streams `append(event)` / `tail(count)`
- `.ltm` — `LongTermMemory`: `save_summary(text)` / `load_summary()` (Redis `ltm:{wf_id}`)
- `.scratch` — in-memory `WorkingScratchpad`
- `RedisMemoryAccessor(redis_store, workflow_id).get(step_id)` — reads `step_output:{wf}:{step}`

#### Phase 9 — Mesh Integration + Auto-Injection
- Before each agent's `setup()`, Mesh injects: `_redis_store`, `_blob_storage`, `mailbox`
- Prometheus server started automatically when `PROMETHEUS_ENABLED=true`
- Agents use injected infrastructure directly — zero boilerplate

### Added — Production Examples
- `examples/ex1_financial_pipeline.py` — AutoAgent autonomous, 3-step financial analysis pipeline (Phases 1, 3, 4, 5, 8, 9)
- `examples/ex2_synthesizer.py` + `ex2_research_node1/2/3.py` — AutoAgent 4-node SWIM research cluster (Phases 4, 7, 8, 9)
- `examples/ex3_support_swarm.py` — CustomAgent P2P, 4-agent support routing + Nexus auth (Phases 1, 4, 7D, 8, 9)
- `examples/ex4_content_pipeline.py` — CustomAgent distributed, content pipeline with LTM (Phases 1, 4, 5, 7, 8, 9)

### Fixed
- `AutoAgent.execute_task`: pass `context=task.get('context')` to `sandbox.execute()` so
  LLM-generated code can access `previous_step_results` (previously caused silent synthesis failures)

### Changed
- Version: 0.3.2 → 0.4.0
- **P2P env var namespace**: `bind_port`, `bind_host`, `seed_nodes`, `node_name` now read from
  `JARVISCORE_BIND_PORT`, `JARVISCORE_BIND_HOST`, `JARVISCORE_SEED_NODES`, `JARVISCORE_NODE_NAME`
  respectively. This isolates per-process P2P settings from the swim package's own env vars.
  In a multi-node deployment each node has a unique port — set it explicitly in the Mesh
  `config` dict or via `JARVISCORE_BIND_PORT` at process launch. Do not set port values in
  a shared `.env` file.
- `.env.example`: `BIND_HOST` / `BIND_PORT` replaced with commented `JARVISCORE_BIND_HOST` /
  `JARVISCORE_BIND_PORT` with guidance on per-process configuration.

---

## [0.3.2] - 2026-02-03

### Added

#### Session Context Propagation
- Added `context` parameter to `notify()`, `request()`, `respond()`, and `broadcast()` methods
- Context carries metadata like mission_id, priority, trace_id across message flows
- `respond()` automatically propagates context from request if not overridden
- `IncomingMessage.context` accessible in all message handlers

```python
# Send request with context
response = await peers.request("analyst", {"q": "..."}, context={"mission_id": "abc"})

# Access context in handler
async def on_peer_request(self, msg):
    mission_id = msg.context.get("mission_id")  # Available!
    return {"result": "..."}
```

#### Mesh Diagnostics
- Added `mesh.get_diagnostics()` method for mesh health monitoring
- Returns: `local_node`, `known_peers`, `local_agents`, `connectivity_status`
- Connectivity status values: `healthy`, `isolated`, `degraded`, `not_started`, `local_only`
- Includes SWIM and keepalive status when P2P is enabled

```python
diag = mesh.get_diagnostics()
print(diag["connectivity_status"])  # "healthy", "isolated", etc.
```

#### Async Request Pattern
- Added `ask_async(target, message, timeout, context)` - returns request_id immediately
- Added `check_inbox(request_id, timeout, remove)` - returns response or None
- Added `get_pending_async_requests()` - list pending async requests
- Added `clear_inbox(request_id)` - clear specific or all inbox entries

```python
# Fire off multiple requests
req_ids = [await peers.ask_async(a, {"q": "..."}) for a in analysts]

# Do other work...
await process_other_tasks()

# Collect responses later
for req_id in req_ids:
    response = await peers.check_inbox(req_id, timeout=5)
```

#### Load Balancing Strategies
- Added `strategy` parameter to `discover()`: `"first"`, `"random"`, `"round_robin"`, `"least_recent"`
- Added `discover_one()` convenience method for single peer lookup
- Added `record_peer_usage(peer_id)` for least_recent tracking

```python
# Round-robin across workers
worker = peers.discover_one(role="worker", strategy="round_robin")

# Least recently used analyst
analyst = peers.discover_one(role="analyst", strategy="least_recent")
```

#### MockMesh Testing Utilities
- Created `jarviscore.testing` module
- `MockPeerClient`: Full mock with discovery, messaging, assertion helpers
- `MockMesh`: Simplified mesh without real P2P infrastructure
- Auto-injects MockPeerClient into agents during MockMesh.start()

```python
from jarviscore.testing import MockMesh, MockPeerClient

mesh = MockMesh()
mesh.add(MyAgent)
await mesh.start()

agent = mesh.get_agent("my_role")
agent.peers.set_mock_response("analyst", {"result": "test"})
agent.peers.assert_requested("analyst")
```

### Testing
- Session context propagation through all messaging methods
- Mesh diagnostics structure and connectivity status values
- Async request/response flow with check_inbox
- Load balancing strategies (first, random, round_robin, least_recent)
- MockMesh and MockPeerClient functionality and assertion helpers

---

## [0.3.1] - 2026-02-02

### Breaking Changes

#### ListenerAgent Removed
- **ListenerAgent has been merged into CustomAgent**
- Migration is simple - just change the import:
  ```python
  # Before
  from jarviscore.profiles import ListenerAgent
  class MyAgent(ListenerAgent): ...

  # After
  from jarviscore.profiles import CustomAgent
  class MyAgent(CustomAgent): ...
  ```
- All handler methods work exactly the same way
- No other code changes required

### Changed

#### CustomAgent Now Includes P2P Handlers
- `on_peer_request(msg)` - Handle incoming requests (return value sent as response)
- `on_peer_notify(msg)` - Handle fire-and-forget notifications
- `on_error(error, msg)` - Handle errors during message processing
- `run()` - Built-in listener loop (no need to write your own)
- Configuration: `listen_timeout`, `auto_respond`

#### Simplified Profile Architecture
| Before (v0.3.0) | After (v0.3.1) |
|-----------------|----------------|
| AutoAgent + CustomAgent + ListenerAgent | AutoAgent + CustomAgent |
| "Which profile do I use?" confusion | Clear: AutoAgent (LLM) or CustomAgent (your code) |

### Documentation
- README.md updated with unified CustomAgent examples
- GETTING_STARTED.md rewritten with framework integration patterns
- CUSTOMAGENT_GUIDE.md updated (ListenerAgent sections removed)
- Added async-first framework guidance (FastAPI, aiohttp, Flask patterns)

---

## [0.3.0] - 2026-01-29

### Added

#### ListenerAgent Profile
- New `ListenerAgent` class for handler-based P2P communication
- `on_peer_request(msg)` handler for incoming requests
- `on_peer_notify(msg)` handler for broadcast notifications
- No more manual `run()` loops required for simple P2P agents

#### FastAPI Integration
- `JarvisLifespan` context manager for 3-line FastAPI integration
- Automatic agent lifecycle management (setup, run, teardown)
- Support for both `p2p` and `distributed` modes
- Import: `from jarviscore.integrations.fastapi import JarvisLifespan`

#### Cognitive Discovery
- `peers.get_cognitive_context()` generates LLM-ready peer descriptions
- Dynamic peer awareness - no more hardcoded agent names in prompts
- Auto-updates when peers join or leave the mesh

#### Cloud Deployment
- `agent.join_mesh(seed_nodes)` for self-registration without central orchestrator
- `agent.leave_mesh()` for graceful departure
- `agent.serve_forever()` for container deployments
- `RemoteAgentProxy` for automatic cross-node agent visibility
- Environment variable support:
  - `JARVISCORE_SEED_NODES` - comma-separated seed node addresses
  - `JARVISCORE_MESH_ENDPOINT` - advertised endpoint for this agent
  - `JARVISCORE_BIND_PORT` - P2P port

### Changed

- Documentation restructured with before/after comparisons
- CUSTOMAGENT_GUIDE.md expanded with v0.3.0 features
- API_REFERENCE.md updated with new classes and methods

### Developer Experience

| Before (v0.2.x) | After (v0.3.0) |
|-----------------|----------------|
| Manual `run()` loops with `receive()`/`respond()` | `ListenerAgent` with `on_peer_request()` handlers |
| ~100 lines for FastAPI integration | 3 lines with `JarvisLifespan` |
| Hardcoded peer names in LLM prompts | Dynamic `get_cognitive_context()` |
| Central orchestrator required | Self-registration with `join_mesh()` |

---

## [0.2.1] - 2026-01-23

### Fixed
- P2P message routing stability improvements
- Workflow engine dependency resolution edge cases

---

## [0.2.0] - 2026-01-15

### Added
- CustomAgent profile for integrating existing agent code
- P2P mode for direct agent-to-agent communication
- Distributed mode combining workflow engine + P2P
- `@jarvis_agent` decorator for wrapping existing classes
- `wrap()` function for wrapping existing instances
- `JarvisContext` for workflow context access
- Peer tools: `ask_peer`, `broadcast`, `list_peers`

### Changed
- Mesh now supports three modes: `autonomous`, `p2p`, `distributed`
- Agent base class now includes P2P support

---

## [0.1.0] - 2026-01-01

### Added
- Initial release
- AutoAgent profile with LLM-powered code generation
- Workflow engine with dependency management
- Sandbox execution (local and remote)
- Auto-repair for failed code
- Internet search integration (DuckDuckGo)
- Multi-provider LLM support (Claude, OpenAI, Azure, Gemini)
- Result storage and code registry

---

*JarvisCore Framework - Build autonomous AI agents with P2P mesh networking.*
