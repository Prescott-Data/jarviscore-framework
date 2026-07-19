---
icon: material/history
hide:
  - toc
---

# Changelog

All notable changes to JarvisCore Framework are documented here. This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

!!! warning "Versioning Policy (effective v1.1.0)"
    Releases prior to v1.1.0 did not follow SemVer consistently — new features
    were shipped in patch releases and a breaking change landed in v0.3.1 (a
    patch). Starting with **v1.1.0**, this project adheres to strict SemVer:

    - **PATCH** (1.1.**x**) — backward-compatible bug fixes only.
    - **MINOR** (1.**x**.0) — new features, new public API surface, backward-compatible behavioral changes.
    - **MAJOR** (**x**.0.0) — breaking changes to the public API.

    Versions **1.0.3** and **1.0.4** contain critical regressions and should be
    avoided. They will be yanked from PyPI. Pin `jarviscore-framework>=1.1.0`.

---

<div class="changelog-release" markdown>

## 1.2.0 <span class="changelog-date">2026-07-19</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/ekizito96" title="Muyukani Ephraim Kizito"><img src="https://github.com/ekizito96.png?size=32" alt="ekizito96"></a>
</div>
</div>

A large, fully backward-compatible release. It hardens the AutoAgent
cognitive stack (context assembly, convergence, planning, evaluation),
adds new orchestration and goal-mode primitives, and makes failures loud
and honest across the board. Every change is additive: no public API was
removed or altered, so upgrading from 1.1.0 is a drop-in.

**Added**

- **[#52] Dynamic fan-out (`mesh.fanout()`)**: run one task template over a runtime list of items with bounded concurrency, first-class partial failure (`collect` or `fail_fast`), per-item timeouts, and explicit aggregation via `.aggregate()` / `.summarize()`. Results are stamped with item and step identity so concurrent items cannot cross-contaminate.
- **[#73] Goal persistence and resume**: goal executions persist after planning, after every completed step, and at terminal states, under `goals/{agent_id}/{goal_id}.json`. `execute_goal(resume_goal_id=...)` rehydrates the plan, facts, and history so a crash loses at most the in-flight step.
- **[#74] Dependency-parallel planning**: the planner declares `depends_on` per step. Steps with no ordering constraint run concurrently (bounded by `MAX_PARALLEL_STEPS`), and a step never runs before its dependencies produce usable output. Plans without dependencies stay strictly sequential.
- **[#72] GOAL STATE context block**: plan facts and completed-step outcomes now cross step boundaries as a structured, named block instead of one clipped generic line.
- **[#69] Generational LTM compaction**: long-term memory is bounded through incremental generational merges rather than unbounded growth or a destructive rewrite, with archives kept for retrieval.
- **[#63] `single_response` execution contract**: AutoAgent can serve a one-completion analysis shape without the full planner or codegen, declared per task. The two-profile model (CustomAgent, AutoAgent) is preserved.
- **[#84] Partial-result preservation**: a goal that stops before completing now returns the work it finished, tagged `[PARTIAL RESULT]`, instead of an empty result. Loud failures stay loud but hand back what they earned.
- **[#86] Local in-memory mailbox**: `MailboxManager` works without Redis for single-process meshes instead of raising `AttributeError`. Multi-node durability still uses Redis.
- **[#88] Registry function identity**: successful coder results carry a `function_id` when a registry function was reused or promoted, so reuse is observable from the envelope.

**Fixed**

- **[#57, #58] Observation and convergence integrity**: the subagent observation channel no longer truncates silently, and the convergence governor stops raising false stalls from content-length equivalence or parameter-blind tool streaks.
- **[#55, #56] Honest context assembly**: every context clip carries an explicit marker, and key-cap overflow is announced by name instead of dropping state silently.
- **[#61, #62] Directive precedence and step identity**: `TOOL` and `DONE` precedence is resolved correctly, and every workflow result carries its `step_id`, including successes.
- **[#59] Zero-loss summarization**: summarization compresses from real evidence and archives originals rather than discarding history.
- **[#60] FailureLedger integrity**: structured-first error classification with aligned guard keys, so retry policy is driven by real error types, not substring guesses.
- **[#81, #82] HITL correctness**: `HITL_ENABLED` is the single opt-in for every escalation path. Goals never dead-end waiting for a human on deployments that did not enable HITL. Evaluator `hitl` verdicts are reserved for genuine human decisions, and the file-backed queue `resolve()` to `check()` round-trip now works.
- **[#85] Evaluator evidence**: the evaluator sees enough of a step's output to judge it (tunable, generous windows with honest truncation markers), ending replan churn caused by verdicts made blind.
- **[#87] Execution-backed coder reasoning**: the coder's system prompt trains it to prove computed answers by executing code rather than answering from memory.

**Changed**

- **[#83] Plan-mode boundary documentation**: clarifies that plan mode is an AutoAgent capability which triages before planning, while CustomAgent treats planning as a library it calls.
- **[#80] Fan-out guide fix**: the workflow guide fan-out example now reads results from `output`, matching the real result shape.
- Documentation accuracy pass: corrected `blob_storage.load()` references to the real `read()` API in the CustomAgent guide and troubleshooting page.
- Removed internal-project references and development artifacts from the public tree.

</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v1.2.0" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

<div class="changelog-release" markdown>

## 1.1.0 <span class="changelog-date">2026-05-12</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/ekizito96" title="Muyukani Ephraim Kizito"><img src="https://github.com/ekizito96.png?size=32" alt="ekizito96"></a>
</div>
</div>

This release fixes all critical regressions introduced in v1.0.3 that rendered AutoAgent unusable, adds new AI engineering primitives (cognitive routing, intent normalization, structured output validation), and marks the beginning of strict SemVer compliance. **Versions 1.0.3 and 1.0.4 are deprecated and will be yanked from PyPI.**

**Fixed**

- **[#32] Output schema enforcement** — `Agent.output_schema` (Pydantic `BaseModel`) is now passed through the Kernel into `CoderSubAgent`, which validates sandbox output against the schema via `model_validate()`. Schema violations fail fast with a clear error instead of silently returning unstructured data.
- **[#33] CoderSubAgent sandbox hallucination** — `CoderSubAgent.get_system_prompt()` now appends a dynamic `SANDBOX ENVIRONMENT` manifest listing all pre-loaded modules and globals in the sandbox namespace. This grounds the LLM in what is actually available, preventing hallucinated imports and undefined-name errors.
- **[#34] Complexity gate before Planner** — `AutoAgent.execute_task()` now runs a `TaskComplexityClassifier` before dispatching to the Planner DAG. Non-complex tasks bypass the full Plan → Execute → Evaluate loop, while classifier contract failures now fail visibly instead of silently falling through to the Planner.
- **[#35] FunctionRegistry semantic search miss** — `CoderSubAgent._tool_check_registry()` now normalizes verbose task descriptions into concise canonical intents via `IntentNormalizer` before calling `semantic_search()`. This eliminates embedding distance drift caused by prompt verbosity.
- **[#36] AutoAgent vs CustomAgent boundary** — Added `p2p_responder` attribute to the `Agent` base class (`False` by default, `True` on `CustomAgent`). `JarvisLifespan` now only creates background `asyncio.Task` instances for agents with `p2p_responder=True`, and raises `RuntimeError` at startup if a `p2p_responder` agent does not override `run()`.
- **[#37] Semantic vs execution status** — `ResultHandler.process_result()` now tracks `semantic_success` separately from execution status. `CoderSubAgent._tool_execute_code()` includes an evaluator hook that flags outputs where `success=False` or `status="failure"` even when the sandbox execution itself succeeded. Fixed `TypeError` when `cost_usd` is `None`.
- **[#38] Sandbox namespace leak into ZMQ coroutine cleanup** — `SandboxExecutor._execute_sync()` and `_execute_async()` now restore `namespace['__builtins__']` to the actual `builtins` module in a `finally` block. This prevents `KeyError: '__builtins__'` crashes in ZMQ's Cython backend during coroutine garbage collection.
- **Structured Kernel routing** — keyword role matching has been replaced by a typed `TaskRouter`. Explicit planner/profile roles are honored first; otherwise the router returns a validated role, confidence, reason, and evidence flag. Invalid or low-confidence routing fails visibly. Custom roles must register `kernel_role_profiles`.
- **Strict subagent completion protocol** — unparseable LLM responses now fail as protocol violations instead of being returned as successful raw content.
- **Coder proof-of-work contract** — `CoderSubAgent` must produce sandbox execution evidence before completion; structured prose results alone are no longer accepted for coder work.
- **Workflow terminal status handling** — only `success` completes a workflow step. `yield`, `hitl`, `blocked`, `error`, and unknown statuses are recorded as failures rather than satisfying dependencies.
- **WorkflowBuilder failure visibility** — agent-returned `failure`, `yield`, `blocked`, `hitl`, or unknown statuses are now preserved instead of being wrapped as step `success`.
- **Distributed workflow output integrity** — a remote step marked `completed` without persisted output now returns failure rather than fabricating a successful empty result.
- **AutoAgent Kernel failure visibility** — Kernel exceptions now return an explicit failure instead of silently falling back to the legacy direct-codegen pipeline.
- **Profile routing explicitness** — missing `default_kernel_role` in a profile no longer implies `communicator`; applications must opt into profile-level routing hints.
- **`_run_context` AttributeError in CoderSubAgent** — Changed direct attribute access to `getattr(self, '_run_context', {})` to prevent `AttributeError` when `_run_context` is not yet initialized.

**Added**

- `TaskComplexityClassifier` (`jarviscore.planning.classifier`) — LLM-based cognitive router that classifies tasks as "trivial", "moderate", or "complex" to determine whether the full Planner DAG is needed.
- `IntentNormalizer` (`jarviscore.execution.intent_normalizer`) — Distills verbose task descriptions into concise canonical intents for accurate embedding-based semantic search.
- `Agent.p2p_responder` attribute — Boolean flag distinguishing reactive task workers (AutoAgent) from proactive mesh citizens (CustomAgent) at the framework level.
- `Agent.output_schema` attribute — Optional Pydantic `BaseModel` class for end-to-end structured output validation through the Kernel pipeline.
- `semantic_success` field in `ResultHandler` result data — Enables downstream consumers to distinguish between "code ran without errors" and "task actually achieved its goal".
- `SandboxExecutor.get_manifest()` / `CoderSandbox.get_manifest()` — Introspect the sandbox namespace for prompt injection into the CoderSubAgent system prompt.

**Deprecated**

- Versions `1.0.3` and `1.0.4` — contain critical AutoAgent regressions. Will be yanked from PyPI. Users should pin `>=1.1.0`.

</div>

---

<div class="changelog-release" markdown>

## 1.0.4 <span class="changelog-date">2026-05-11</span> {: .changelog-deprecated }

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/ekizito96" title="Muyukani Ephraim Kizito"><img src="https://github.com/ekizito96.png?size=32" alt="ekizito96"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v1.0.4" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Documentation**

- Mobile drawer fully resolved: Level 1 nav items clickable on all viewports, back arrow restored, site name text hidden in mobile view.
- Section `index.md` entry points added for Concepts, Guides, and Reference — each section now has an overview landing page with icon cards.
- CSS tab icons removed from sections that use frontmatter-defined icons, eliminating duplication.
- README expanded and restructured with additional examples and API reference.

**Fixed**

- Deprecated `Mesh(mode='distributed')` calls replaced with explicit `config={"p2p_enabled": True}` in `test_09_distributed_autoagent.py` and `test_10_distributed_customagent.py`.

</div>

---

<div class="changelog-release" markdown>

## 1.0.3 <span class="changelog-date">2026-05-08</span> {: .changelog-deprecated }

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/ekizito96" title="Muyukani Ephraim Kizito"><img src="https://github.com/ekizito96.png?size=32" alt="ekizito96"></a>
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
<a href="https://github.com/sangalo20" title="Sangalo Mwenyinyo"><img src="https://github.com/sangalo20.png?size=32" alt="sangalo20"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v1.0.3" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Documentation**

- Launched the full MkDocs documentation site — Getting Started, Concepts, Guides, Reference, Examples, and Enterprise sections.
- New guides: AutoAgent, CustomAgent, Workflows, Chat, HITL, Nexus, Knowledge Base, System Prompts, Observability, FastAPI Integration, Internet Search, Migration (CrewAI + LangGraph), Testing.
- New concept pages: Architecture, Memory, Nexus, P2P, System Bundles, Agent Personas.
- New examples: Financial Pipeline, Research Network, Support Swarm, Content Pipeline, Investment Committee.
- Synced all 15 brand SVG variants to `docs/assets/` and removed legacy unreferenced `logo.png` / `logo.svg`.
- `guides/testing.md`: documented `ExampleMockLLMClient` — tool-validating mock LLM for unit testing agents with tool use.
- Fixed deprecated `Mesh(mode=...)` calls in `README.md`, `guides/production.md`, `guides/browser-automation.md`, and `guides/adapters.md`.

**Added**

- `mesh.run_task(agent, task, context, complexity)` — primary user-facing API for dispatching a single task to an agent by role with multi-tier model routing.
- `P2P_ENABLED=true` env var support — `Settings.p2p_enabled` is now merged into Mesh config at startup.
- `HITLCategory` enum with hard enforcement on `HITLQueue.request()` — valid categories: `auth_required`, `data_required`, `critical_action`. Invalid categories raise `ValueError`.
- Planner subagent hints are strict — valid hints are accepted exactly and invalid hints fail visibly instead of being remapped.
- `STEP_OUTPUT_MAX_BYTES` (default 200 KB) and `STEP_OUTPUT_PREVIEW_BYTES` (default 20 KB) — large step outputs stored as truncated preview with `_overflow` flag.
- Idempotent write guard on `RedisStore.save_step_output()` — a successful result will not be overwritten by a subsequent error payload from a stalled re-execution.
- Azure Content Filter visibility in `LLMClient` — raw provider content-filter rejections now fail visibly by default. `AZURE_CONTENT_FILTER_REPAIR_ENABLED=true` explicitly opts into Azure-specific prompt repair after the raw prompt is rejected.
- `Kernel._get_model_for_tier()` — clean multi-tier model resolution: complexity hint → `TASK_MODEL_NANO` / `TASK_MODEL_STANDARD` / `TASK_MODEL_HEAVY` → legacy fallback.
- `MailboxManager` schema normalisation — handles both the current flat envelope schema and the pre-v1.0.2 double-nested schema transparently.
- **Vertex AI provider** (`LLMProvider.VERTEX_AI`): GCP-native Gemini access via Application Default Credentials (ADC). No API key required — authenticate with `gcloud auth application-default login` or attach a service account. Config: `VERTEX_AI_ENABLED=true`, `VERTEX_AI_PROJECT`, `VERTEX_AI_LOCATION` (default `us-central1`), `VERTEX_AI_MODEL` (default `gemini-2.5-flash`). Slots into the fallback chain after Gemini: **Azure → Claude → vLLM → Gemini → Vertex AI**.
- `_normalize_tools_for_gemini()` static method — auto-converts tool schemas to Gemini `function_declarations` format. Accepts Anthropic/PeerTool (`input_schema`), flat (`name`+`parameters`), or already-native formats.
- Shared `_call_genai_client()` helper: both `_call_gemini` and `_call_vertex_ai` delegate here for consistent token accounting and cost calculation.
- Tool-call response parsing in `_call_genai_client`: when a Gemini/Vertex AI response contains `function_call` parts, `tool_calls` is populated and `content` is set to `""`.
- Token pricing entries for `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3.1-pro`, `gemini-3.1-pro-preview`.
- Process-wide LLM concurrency semaphore (`LLM_MAX_CONCURRENT` env var) — prevents thundering-herd 429s in multi-agent deployments.
- `llm.nano_model` and `llm.planner_model` properties — tier-aware model selection for `StepEvaluator` and `Planner`.
- `max_completion_tokens` alias in `generate()` — callers can use GPT-5.x SDK naming convention interchangeably with `max_tokens`.

**Fixed**

- `P2P_ENABLED` env var was not forwarded to `Mesh.config`, requiring `config={"p2p_enabled": True}` explicitly even when the env var was set.
- HITL escalations could be raised for arbitrary reasons, polluting the human review queue. Now enforced at the framework level.
- Planner emitted `Unknown subagent_hint` warnings for semantically valid but aliased LLM role names.
- Examples audit (2026-05-07): fixed API compatibility across all 5 production examples for v1.0.3 breaking changes.
- SWIM stabilisation replaced hardcoded 5 s sleep with condition-based poll (0.3 s for single-node; up to 5 s when seed nodes configured).
- `AutoAgent` result dict now exposes `payload` as a dedicated top-level key when the output is a structured dict, enabling downstream step access without manual parsing.
- Crash recovery `_resume()` pre-populates recovered step results into `pre_results` so resumed workflows replay correctly rather than skipping completed steps.
- `ExampleMockLLMClient` validates tool names against the `tools` parameter before returning tool-use responses, preventing mock deadlocks when a tool is out of scope.
- `_call_gemini` now forwards `**kwargs` (including `tools`) to `_call_genai_client`, making Gemini tool-calling behaviour consistent with Vertex AI.
- `test_claude_primary` now passes an explicit config that disables all other providers, making the assertion environment-independent.

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

## 0.4.0 <span class="changelog-date">2026-02-19</span>

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

The `Kernel` replaces AutoAgent's linear codegen → sandbox → repair pipeline with a supervised OODA loop. `ExecutionLease` enforces token/turn/wall-clock budgets per subagent role. `AgentCognitionManager` tracks budget spend per phase, detects spinning (same tool 3+ times), and enforces cognitive gates. `AdaptiveHITLPolicy` with `HumanTask` pauses execution when confidence or risk triggers fire. Coder dispatches require executable proof of work before completion.

**Phase 7 — Distributed WorkflowEngine**

`WorkflowEngine` persists DAG to Redis hash `workflow_graph:{wf_id}` for crash recovery. When no local agent matches a step, the engine resets status to `"pending"` and polls Redis. `Mesh._run_distributed_worker()` scans `jarviscore:active_workflows`, checks `are_dependencies_met()`, atomically claims steps via SETNX, executes, and writes output to Redis.

**Phase 7D — AuthenticationManager (Nexus)**

Set `requires_auth = True` on any agent and the Mesh injects `self._auth_manager` before `setup()`. Full NexusClient flow: `request_connection → browser OAuth → poll ACTIVE → resolve_strategy → apply headers`. Graceful degradation when `NEXUS_GATEWAY_URL` is not set.

**Phase 8 — Memory Architecture**

`UnifiedMemory(workflow_id, step_id, agent_id, redis_store, blob_storage)` with `.episodic` (EpisodicLedger via Redis Streams), `.ltm` (LongTermMemory via Redis), and `.scratch` (in-memory WorkingScratchpad). `RedisMemoryAccessor` reads step outputs across the workflow.

**Phase 9 — Mesh Integration and Auto-Injection**

Before each agent's `setup()`, the Mesh injects `_redis_store`, `_blob_storage`, and `mailbox`. Prometheus server starts automatically when `PROMETHEUS_ENABLED=true`. Agents use injected infrastructure directly with zero boilerplate.

**Production Examples**

- `financial_pipeline.py` — AutoAgent autonomous, 3-step financial analysis pipeline.
- `research_synthesizer.py` + `research_node_1/2/3.py` — AutoAgent 4-node SWIM research cluster.
- `support_swarm.py` — CustomAgent P2P, 4-agent support routing with Nexus auth.
- `content_pipeline.py` — CustomAgent distributed, content pipeline with LTM.

**Fixed**

- `AutoAgent.execute_task`: pass `context=task.get('context')` to `sandbox.execute()` so LLM-generated code can access `previous_step_results`.

**Changed**

- P2P env var namespace: `bind_port`, `bind_host`, `seed_nodes`, `node_name` now read from `JARVISCORE_BIND_PORT`, `JARVISCORE_BIND_HOST`, `JARVISCORE_SEED_NODES`, `JARVISCORE_NODE_NAME` respectively. This isolates per-process P2P settings from the swim package's own env vars.

</div>

---

<div class="changelog-release" markdown>

## 0.3.2 <span class="changelog-date">2026-02-04</span>

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

## 0.2.0 <span class="changelog-date">2026-01-22</span>

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

## 0.1.1 <span class="changelog-date">2026-01-16</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.1.1" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Changed**

- Migrated from the deprecated `google.generativeai` SDK to the current `google.genai` SDK.
- Updated default Gemini model to `gemini-2.0-flash`.

**Added**

- Scaffold CLI (`python -m jarviscore.cli.scaffold`) for new project initialization.
- Bundled `.env.example` and example files in the PyPI distribution.

</div>

---

<div class="changelog-release" markdown>

## 0.1.0 <span class="changelog-date">2026-01-13</span>

<div class="changelog-meta" markdown>
<div class="changelog-contributors">
<a href="https://github.com/Ruth-mutua" title="Ruth Mutua"><img src="https://github.com/Ruth-mutua.png?size=32" alt="Ruth-mutua"></a>
</div>
<a class="changelog-release-link" href="https://github.com/Prescott-Data/jarviscore-framework/releases/tag/v0.1.0" target="_blank" rel="noopener noreferrer">View release on GitHub →</a>
</div>

**Added**

Initial release. AutoAgent profile with LLM-powered code generation. Workflow engine with dependency management. Sandbox execution (local and remote). Auto-repair for failed code. Internet search integration (DuckDuckGo). Multi-provider LLM support (Claude, OpenAI, Azure, Gemini). Result storage and code registry.

</div>
