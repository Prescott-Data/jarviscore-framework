# Changelog

All notable changes to JarvisCore Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
