# Changelog

All notable changes to JarvisCore Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
