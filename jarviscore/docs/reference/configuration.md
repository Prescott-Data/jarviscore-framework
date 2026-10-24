---
icon: material/tune
title: "JarvisCore Environment Configuration Reference"
description: "Configure LLM providers, Redis, storage, Nexus, observability, peer-to-peer networking, browser automation, and sandbox execution."
---

# Configuration Reference

This is the complete reference for all JarvisCore environment variables. Copy `.env.example` from your project root after running `jarviscore init`, populate one LLM section, and run `jarviscore check` to validate.

---

## LLM Providers

Configure exactly one LLM provider. JarvisCore auto-detects the active provider from the environment variables present. The promotional provider is selected first when its token is present. The existing provider order after it is Azure → Claude → vLLM → Gemini → Vertex AI.

### Existing Prescott promotional entitlement

Organizations that already received a Prescott promotional entitlement can set
`JARVISCORE_PROMO_TOKEN`. This is a limited, revocable entitlement token, not an
upstream model-provider API key. There is currently no public self-service
enrollment page. Promotional access is selected first when configured. Expiry,
exhaustion, and service errors fail explicitly and never silently fall through
to another configured paid provider.

Every promotional call preserves the complete request and HTTP response under a
stable call ID in `./.jarviscore/traces/promo_calls`. Set
`JARVISCORE_PROMO_RAW_ARTIFACT_DIR` to choose another local directory.

| Variable | Required | Default | Description |
|---|---|---|---|
| `JARVISCORE_PROMO_TOKEN` | Yes | (none) | Unique promotional entitlement issued by Prescott |
| `JARVISCORE_PROMO_RAW_ARTIFACT_DIR` | No | `./.jarviscore/traces/promo_calls` | Durable complete call artifacts |

=== "Anthropic Claude"

    | Variable | Required | Default | Description |
    |---|---|---|---|
    | `CLAUDE_API_KEY` | Yes | (none) | API key starting with `sk-ant-` |
    | `CLAUDE_MODEL` | No | `claude-sonnet-4` | Model name |

=== "Google Gemini"

    | Variable | Required | Default | Description |
    |---|---|---|---|
    | `GEMINI_API_KEY` | Yes | (none) | API key starting with `AIza` |
    | `GEMINI_MODEL` | No | `gemini-2.0-flash` | Model name |

=== "Azure OpenAI"

    | Variable | Required | Default | Description |
    |---|---|---|---|
    | `AZURE_API_KEY` | Yes | (none) | Azure OpenAI API key |
    | `AZURE_ENDPOINT` | Yes | (none) | Resource endpoint, e.g. `https://your-resource.openai.azure.com/` |
    | `AZURE_DEPLOYMENT` | Yes | (none) | Deployment name, e.g. `gpt-4o` |
    | `AZURE_API_VERSION` | No | `2024-10-21` | Azure OpenAI dated GA data-plane API version; override when your deployment requires another supported version |

=== "Local / vLLM"

    | Variable | Required | Default | Description |
    |---|---|---|---|
    | `LLM_ENDPOINT` | Yes | (none) | OpenAI-compatible endpoint URL |
    | `LLM_MODEL` | Yes | (none) | Model name as expected by the endpoint |

---

## Multi-Tier Model Routing

The Kernel uses two base models that are always active, plus three optional tier overrides. Pass `complexity=` in workflow step dicts to select a tier.

```python
await mesh.workflow("task-001", [
    {"agent": "analyst", "task": "...", "complexity": "nano"},
    {"agent": "analyst", "task": "...", "complexity": "heavy"},
])
```

**Base models (always active)**

| Variable | Default | Description |
|---|---|---|
| `CODING_MODEL` | `dromos-gpt-4.1` | Model used by `CoderSubAgent` for all code generation. |
| `TASK_MODEL` | `gpt-4o` | Model used by Researcher, Communicator, and Browser sub-agents when no tier override is set. |

**Tier overrides (optional)**

| Variable | Tier | Recommended use |
|---|---|---|
| `TASK_MODEL_NANO` | `nano` | Classification, summarisation, simple transforms |
| `TASK_MODEL_STANDARD` | `standard` | General tasks; the default when `complexity` is not specified |
| `TASK_MODEL_HEAVY` | `heavy` | Deep reasoning, long-context analysis, architecture decisions |

When a tier variable is not set, the Kernel falls back to `TASK_MODEL`.

**LLM reliability tuning**

These become important once you run more than two agents concurrently against a rate-limited API.

| Variable | Default | Description |
|---|---|---|
| `LLM_TIMEOUT` | `120.0` | Seconds before an LLM call times out. |
| `LLM_CONNECT_TIMEOUT` | `10.0` | Seconds to establish the connection (TCP and TLS), separate from `LLM_TIMEOUT`. |
| `LLM_KEEPALIVE_SECONDS` | `120.0` | Seconds an idle provider connection is kept for the next call (Azure, Claude, the promotion endpoint and vLLM). The SDK default of 5 s is shorter than the tool work between agent turns, so most calls reconnected; keep this below your provider's idle timeout (Azure: 240 s). |
| `LLM_PREWARM` | `true` | Open the primary provider's connection while an agent starts, so its first call skips the TCP and TLS handshake. Only a bare request to the provider's host is sent; a failed warm-up is ignored. |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature for all providers. |
| `LLM_MAX_CONCURRENT` | `0` | Most calls in flight per deployment. `0` leaves the governor to find the level (up to `LLM_CONCURRENCY_CEILING`). With the governor disabled, a process-wide cap. |
| `LLM_MAX_RETRIES_429` | `4` | Retry attempts when a provider returns 429 before giving up. |
| `LLM_429_BASE_DELAY` | `2.0` | Exponential backoff base delay in seconds. Actual delay: `min(base × 2^attempt, 60s)`. |
| `LLM_MODEL_OUTPUT_LIMITS` | `{}` | JSON map of model or deployment name to its completion-token ceiling, e.g. `{"gpt-5.2-chat": 128000}`. Calls that do not set `max_tokens` receive the serving model's declared ceiling, bounded by the remaining workflow budget. Declare reasoning models here: their hidden reasoning is billed against the same allowance. |
| `LLM_DEFAULT_MAX_TOKENS` | `4000` | Output allowance for calls to models without a declared ceiling. |
| `LLM_PRICES` | `{}` | JSON map of model or deployment name to its price per 1M tokens, e.g. `{"gpt-5.6-luna": {"input": 1.25, "output": 10.0, "cached": 0.125}}`. Declared prices override the built-in table. Cached input is billed at `cached` when given. A model with no known price is costed at $3/$15 per 1M input/output tokens, logged once as an estimate, and its calls report `price_source: "default"`. |
| `AZURE_CONTENT_FILTER_REPAIR_ENABLED` | `false` | Opt into an Azure-specific content-filter retry that applies a provider-safe preamble and neutral wording after the raw prompt is rejected. Off by default so prompt rewriting never hides developer intent. |

### Provider governor

Every model call is admitted per deployment (for example `azure:gpt-4o`)
before it is sent. Calls in flight start at `LLM_INITIAL_CONCURRENCY`, grow
while the provider keeps up, and halve on a 429 or near-empty rate-limit
headers. None of these needs setting.

| Variable | Default | Description |
|---|---|---|
| `LLM_GOVERNOR_ENABLED` | `true` | Admit every call through the governor. |
| `LLM_LIMITS` | `{}` | Known limits per deployment, enforced in a 60 s window shared through Redis by every process, e.g. `{"azure:gpt-4o": {"rpm": 3000, "tpm": 1000000}}`. |
| `LLM_INITIAL_CONCURRENCY` | `8` | Calls in flight per deployment at start. |
| `LLM_CONCURRENCY_CEILING` | `256` | Most calls in flight per deployment the governor will grow to. |
| `LLM_BULK_RESERVE` | `0.15` | Share of a deployment's calls in flight held back from bulk work for interactive calls. |

Run background work in the bulk lane so people waiting on chat keep headroom:

```python
from jarviscore.execution.governor import BULK, lane_scope

with lane_scope(BULK):
    await mesh.execute_goal("Re-verify every claim in the data room")
```

---

## Decision Models: TypeSafe Jev

TypeSafe Jev is an optional decision model for typed `Choice`, `Score`, and
`Noul` judgments. Install `jarviscore-framework[typesafe]`. AutoAgent still
requires one generative LLM provider from the preceding section.

| Variable | Default | Description |
|---|---|---|
| `DECISION_CLIENT_FACTORY` | (none) | `module:callable` returning any `DecisionClient`; takes precedence over `TYPESAFE_API_KEY`. See [Bring any decision model](../concepts/decision-models.md#bring-any-decision-model). |
| `TYPESAFE_API_KEY` | (none) | Enables the shared Jev decision client. |
| `TYPESAFE_DEFAULT_MODEL` | `jev-latest` | TypeSafe model used for decisions. |
| `TYPESAFE_BASE_URL` | TypeSafe SDK default | Optional compatible gateway or test endpoint. |
| `TYPESAFE_TIMEOUT` | `10.0` | Decision request timeout in seconds. |
| `KERNEL_ROUTER_PROVIDER` | `llm` | Set to `typesafe` to opt into Jev-backed Kernel role selection. |
| `KERNEL_ROUTER_MAY_ANSWER` | `true` | Let the router answer, in the same call, a task that needs no role (summarising, rewording, explaining or drafting from the task text, with no tool, data, calculation or action). Applies only when the router runs on the model the communicator would use. |
| `TYPESAFE_ROUTER_MIN_CONFIDENCE` | `0.5` | Minimum Jev routing confidence. Validate against your workload before changing production behavior. |
| `TASK_COMPLEXITY_PROVIDER` | `llm` | Set to `typesafe` to classify direct Kernel versus Planner execution with Jev. |
| `TYPESAFE_COMPLEXITY_MIN_CONFIDENCE` | `0.5` | Below this confidence, preserve the full planning path. |
| `RAG_DECISION_PROVIDER` | `vector` | Set to `typesafe` to classify the FAISS shortlist before Researcher consumes it. |
| `RAG_TYPESAFE_MAX_CONCURRENT` | `4` | Maximum concurrent passage-classification calls. |
| `RAG_TYPESAFE_INJECTION_MAX` | `0.70` | Exclude passages above this prompt-injection probability. Advisory, not a security boundary. |
| `RAG_TYPESAFE_CONTRADICTS_MIN` | `0.70` | Route passages above this premise-conflict probability to the conflict set. |
| `RAG_TYPESAFE_RELEVANT_MIN` | `0.45` | Exclude passages below this relevance probability. |
| `RAG_TYPESAFE_EVIDENCE_MIN` | `0.55` | Include passages above this usable-evidence probability after earlier checks. |
| `TYPESAFE_INPUT_COST_PER_MILLION_USD` | `0.042` | Input-token price used for workflow cost accounting; update if TypeSafe pricing changes. |

See [Decision Models](../concepts/decision-models.md) for agent APIs, routing
precedence, privacy boundaries, and examples.

---

## Redis

Without Redis, JarvisCore runs in in-process mode: workflows execute locally, mailboxes are file-backed, and distributed features are unavailable. With Redis, the following capabilities become active: distributed workflow DAGs, durable mailboxes, cross-node step claiming, episodic ledger, and LTM compression.

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | (none) | Full connection URL; takes precedence over host/port variables. Example: `redis://host:6379/0` |
| `REDIS_HOST` | `localhost` | Used when `REDIS_URL` is not set |
| `REDIS_PORT` | `6379` | Used when `REDIS_URL` is not set |
| `REDIS_PASSWORD` | (none) | Authentication password |
| `REDIS_DB` | `0` | Database number |
| `REDIS_CONTEXT_TTL_DAYS` | `7` | Number of days to retain agent context keys |

Start Redis locally for development:

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

### Distributed goal configuration

These values are `Mesh(config={...})` keys, not environment variables:

| Key | Default | Description |
|---|---|---|
| `distributed_poll_interval` | `2.0` | Redis DAG polling interval in seconds |
| `distributed_claim_lease_seconds` | `60` | Renewable execution-claim lease duration |
| `mesh_planning_lease_seconds` | `300` | Initial planning and amendment lease duration |
| `mesh_max_reconciliation_revisions` | `3` | Bounded automatic semantic revisions |
| `mesh_response_capability` | `None` | Capability authorized for the optional final response |
| `mesh_planning_brief` | `None` | Trusted product mandate, operating method and negative-result evidence standard used for DAG draft, audit, repair and reconciliation; never used to extract source obligations |
| `execution_budget` | framework defaults | Shared `max_seconds`, `max_steps`, `max_replans`, `max_tokens`, `max_epochs_per_step`, `max_peer_depth` and `peer_timeout_seconds` |
| `workspace_required` | `false` | Fail before planning unless a trusted source adapter produces a verified snapshot |
| `workspace_source_adapters` | `{}` | Provider names mapped to `SourceAdapter` implementations |
| `workspace_source_catalog` | built-in provider descriptions | Trusted provider descriptions used to resolve explicit source identity from a goal |
| `workspace_source_resolver` | planning-model resolver | Optional trusted callable that returns source identity before adapter capture |
| `workspace_snapshot_limits` | framework defaults | Trusted `max_files`, `max_total_bytes`, `max_file_bytes`, and acquisition `concurrency` limits enforced before planning |
| `workspace_allowed_commands` | `[]` | Additional trusted executable names available to `workspace_run`; caller context cannot expand this list. A node that sets it decides for every step it runs, whoever asked |
| `workspace_command_timeout_seconds` | `120` | Trusted per-command workspace limit; a timeout is evidence and does not stop the DAG |
| `workspace_command_environment` | `{}` | Trusted recognized package-manager cache paths passed without inheriting parent secrets |
| `workspace_delta_ignored_names` | runtime/build defaults | Directory names excluded from persisted deltas, including `.git`, `.venv`, `node_modules`, `output`, and `target` |

Caller task context cannot override execution authority or the workflow budget.
All nodes sharing one distributed DAG should run the same JarvisCore minor
version. See [Durable Goal Execution](../guides/goal-execution.md).

---

## Memory: Athena MemOS

Athena provides three-tier persistent memory (STM, MTM, and LTM graph) that spans sessions. Without Athena, agents use Redis-only episodic memory for the current session.

| Variable | Default | Description |
|---|---|---|
| `ATHENA_URL` | (none) | Athena API base URL, e.g. `http://localhost:8080` |
| `ATHENA_TENANT_ID` | `default` | Tenant namespace for memory isolation across teams or environments |
| `ATHENA_HTTP_TIMEOUT` | `10.0` | Seconds before an Athena HTTP call times out. Increase if your Athena instance is remote or under load. |
| `ATHENA_SESSION_TTL_DAYS` | `30` | How long a session ID is cached in Redis before Athena re-issues it. |
| `ATHENA_API_KEY` | — | Optional API key sent as `X-API-Key`. Keep it out of prompts and logs. |
| `ATHENA_JWT_TOKEN` | — | Optional JWT sent as `X-JWT-Token` for tenant/user isolation. |
| `ATHENA_PORT` | `8080` | Host port for the Athena server when the stack is started by `memory init` |

Every published port in the local stack is overridable for co-located deployments: `ATHENA_REDIS_PORT` (6380), `ATHENA_MONGO_PORT` (27017), `ATHENA_MINIO_PORT` (9000), `ATHENA_MINIO_CONSOLE_PORT` (9001), `ATHENA_MILVUS_PORT` (19530), `ATHENA_MILVUS_METRICS_PORT` (9091), `ATHENA_ARANGO_PORT` (8529).

Azure OpenAI is detected automatically by `memory init` when `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` are set (deployment name from `AZURE_DEPLOYMENT`, default `gpt-4o`).

Initial setup:

```bash
git clone https://github.com/Prescott-Data/athena ~/athena
jarviscore memory init
```

If your Athena clone is not at `~/athena`:

```bash
ATHENA_DIR=/path/to/athena jarviscore memory init
```

---

## Storage: Blob

Blob storage is used by agents to persist large outputs (reports, datasets, generated files) and by `WorkingScratchpad` for per-step working notes. The local backend is always active by default.

| Variable | Default | Description |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local`, `azure`, or `redis` (file contents in `REDIS_URL`, so one Redis serves every machine) |
| `STORAGE_BASE_PATH` | `./.jarviscore/blob_storage` | Base directory path for the local backend |
| `STORAGE_REDIS_MAX_BLOB_BYTES` | `33554432` | Largest single file the `redis` backend accepts |
| `AZURE_STORAGE_CONNECTION_STRING` | (none) | Required when `STORAGE_BACKEND=azure` |

For Azure:

```bash
pip install "jarviscore-framework[azure]"
```

```bash title=".env"
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
```

---

## Search

### Provider deadlines

| Variable | Default | Description |
|---|---|---|
| `RESEARCH_GROUNDED_TIMEOUT_SECONDS` | `45` | Per-call deadline for Google Grounded (generative search) |
| `RESEARCH_SEARCH_TIMEOUT_SECONDS` | `15` | Per-call deadline for each other search provider |
| `RESEARCH_ALLOW_WIKIPEDIA_FALLBACK` | `false` | Search Wikipedia when no other provider found anything, even with web providers configured |

Both `InternetSearch` implementations accept `grounded_timeout_seconds` and
`search_timeout_seconds` keyword arguments, which take precedence over these
environment variables. Values must be positive finite seconds. For example,
`InternetSearch(grounded_timeout_seconds=60, search_timeout_seconds=20)`.
These deadlines bound each provider including its retries; existing HTTP-request
timeouts still apply. They do not change agent leases or the overall task budget.
Timeout diagnostics identify the provider, exception type and configured deadline.

### Crawler identity

| Variable | Default | Description |
|---|---|---|
| `RESEARCH_USER_AGENT` | A desktop browser string | `User-Agent` sent when research fetches pages and PDFs. Public registers such as SEC EDGAR admit automated clients only when they declare who they are, for example `Acme Research research@acme.example`. Both `InternetSearch` implementations also accept a `user_agent` argument. |

JarvisCore runs multiple search providers in parallel and merges results. All providers have circuit breakers: a failing provider is skipped automatically. See the [Internet Search guide](../guides/internet-search.md) for provider details, ranking logic, and usage patterns.

### Google Grounded Search <span class="jc-badge jc-badge-primary">Primary</span>

Active automatically when `GEMINI_API_KEY` is set (which is already required for agents). No extra configuration needed.

| Variable | Default | Description |
|---|---|---|
| `GEMINI_GROUNDING_API_KEY` | `GEMINI_API_KEY` | Override the key used specifically for grounded search |
| `GEMINI_GROUNDING_MODEL` | `gemini-2.5-flash` | Gemini model used for grounded search |
| `GOOGLE_CLOUD_PROJECT` | (none) | Vertex AI path (alternative to API key) |
| `GOOGLE_CLOUD_LOCATION` | `global` | GCP location for Vertex AI |

### Serper <span class="jc-badge jc-badge-optional">Optional</span>

| Variable | Default | Description |
|---|---|---|
| `SERPER_API_KEY` | (none) | API key from [serper.dev](https://serper.dev). Provider is skipped if unset. |

### SearXNG <span class="jc-badge jc-badge-optional">Optional</span> <span class="jc-badge jc-badge-free">Self-hosted</span>

| Variable | Default | Description |
|---|---|---|
| `SEARXNG_INSTANCE_URL` | `http://localhost:8080` | URL of your SearXNG instance. Provider is skipped if unreachable. |

### Research & PDF tuning

| Variable | Default | Description |
|---|---|---|
| `RESEARCH_PDF_TIMEOUT_SECONDS` | `90` | Timeout for PDF download and extraction |
| `RESEARCH_PDF_MAX_RETRIES` | `3` | Retry attempts for PDF extraction |

---

## Browser Automation

Enables web navigation, form interaction, and structured scraping via `BrowserSubAgent`.

```bash
pip install "jarviscore-framework[browser]"
playwright install chromium
```

| Variable | Default | Description |
|---|---|---|
| `BROWSER_ENABLED` | `false` | Enable `BrowserSubAgent` |
| `BROWSER_HEADLESS` | `true` | Run the browser in headless mode |
| `BROWSER_SITE_INTERVAL_S` | `1.5` | Seconds between requests to the same site |
| `BROWSER_SETTLE_TIMEOUT_MS` | `3000` | How long a page may keep changing after an action before the agent looks again |
| `BROWSER_DATA_TIMEOUT_MS` | `10000` | Longest an action waits for the site's own data requests to finish |
| `BROWSER_CODE_TIMEOUT_S` | `600` | Default and maximum program duration; also bounded by the remaining execution lease |
| `BROWSER_PARALLEL_PAGES` | `4` | Pages `read_pages` opens at once in a run's browser session |
| `BROWSER_HISTORY_PAGES` | `50` | Most pages `read_pages` turns through one history before reporting that it goes on (`more`) |
| `BROWSER_ACT_MIN_CONFIDENCE` | `0.7` | Decision confidence at which `act` performs the action itself; below it, `act` returns candidates |
| `BROWSER_CONTINUATION_HOLD_S` | `120` | How long a browser stays open for the step's next execution epoch to continue on the same page |
| `BROWSER_LOCALE` | host's | Locale the browser presents, e.g. `en-GB`; match it to the egress proxy's region |
| `BROWSER_TIMEZONE` | host's | IANA timezone the browser presents, e.g. `Europe/London` |

---

## Egress Proxy

JarvisCore supplies no IP addresses. To give agents a reputable, stable or regional exit, point them at your own proxy provider. The browser and the pages the researcher reads leave through it; search-provider APIs, LLM calls and Nexus do not.

| Variable | Default | Description |
|---|---|---|
| `EGRESS_PROXY_URL` | (none) | `http://` or `https://` proxy, e.g. `http://user-session-{session}:pass@gw.provider.example:7000`. `{session}` becomes a stable 16-character id per tenant profile or workflow, so a provider that pins an exit IP per session keeps one IP for a login or checkout. |
| `EGRESS_PROXY_BYPASS` | (none) | Comma-separated hosts that go direct, e.g. `searxng,.internal`. Loopback always goes direct. |

See [Browser Automation: Your own proxy](browser.md#your-own-proxy).

---

## Nexus: Credential Management

Required only when agents call third-party services (GitHub, Slack, Jira, Stripe, and so on) through providers registered with `requires_auth = True`.

| Variable | Default | Description |
|---|---|---|
| `NEXUS_GATEWAY_URL` | (none) | Gateway URL, e.g. `http://localhost:8090` |
| `NEXUS_GATEWAY_API_KEY` | (none) | Sent as `X-API-Key` on every Gateway call. Written by `jarviscore nexus init`. Grants Gateway access only, never the broker's encryption key. |
| `NEXUS_BROKER_URL` | (none) | Broker URL, e.g. `http://localhost:8080`. Used by dashboard and SDK to POST credentials directly to the Broker's `/auth/capture-credential` endpoint for non-OAuth providers. |
| `NEXUS_RETURN_URL` | `http://localhost:8000/oauth/callback` | OAuth callback URL; the Nexus broker redirects here after consent. |
| `NEXUS_DEFAULT_USER_ID` | `jarviscore-agent` | User identity passed to Nexus for credential lookups. |
| `AUTH_STRATEGY_CACHE_TTL` | `300` | Seconds before the resolved auth strategy is re-fetched from the Gateway. |
| `AUTH_FLOW_TIMEOUT` | `300` | Maximum seconds to wait for a user to complete OAuth browser consent. |
| `AUTH_POLL_INTERVAL` | `2.0` | Seconds between Gateway status polls during an OAuth flow. |
| `AUTH_OPEN_BROWSER` | `true` | Whether to open the system browser automatically when OAuth consent is needed. |

Initial setup:

```bash
jarviscore nexus init
jarviscore nexus register github --client-id=YOUR_ID   # prompts for the secret
jarviscore nexus test github
```

The local stack's own secrets (`NEXUS_ENCRYPTION_KEY`, `NEXUS_STATE_KEY`, `NEXUS_BROKER_API_KEY`) live in `~/.jarviscore/nexus/stack.env` and are read by the broker and gateway containers only. Do not put them in a project `.env`.

---

## P2P / SWIM Mesh

Enables multi-node agent discovery and message routing using the SWIM gossip protocol and ZMQ transport. Requires Redis for distributed workflow coordination.

| Variable | Default | Description |
|---|---|---|
| `P2P_ENABLED` | `true` | Enables SWIM/ZMQ when the optional `p2p` dependencies are installed; set `false` to force local-only peers |
| `JARVISCORE_BIND_HOST` | `127.0.0.1` | Per-process bind address; use `0.0.0.0` for a node reachable from other machines |
| `JARVISCORE_BIND_PORT` | `7946` | Per-process SWIM gossip port; ZMQ uses this port plus `1000` |
| `JARVISCORE_SEED_NODES` | (none) | Comma-separated seed addresses, for example `10.0.0.1:7946,10.0.0.2:7946` |

!!! warning "Port uniqueness"
    `JARVISCORE_BIND_PORT` must be different for each node running on the same machine. The ZMQ data port is set automatically to `JARVISCORE_BIND_PORT + 1000`.

The seed node does not set `JARVISCORE_SEED_NODES`. All other nodes point at the seed node (or any other live node) to join the cluster. Keep these bind settings per process rather than in a shared `.env` file.

---

## Kernel Tuning

Advanced execution parameters for the OODA loop Kernel. The defaults are appropriate for the majority of workloads.

**Execution limits**

| Variable | Default | Description |
|---|---|---|
| `KERNEL_MAX_TURNS` | `30` | Maximum OODA loop turns per task execution. |
| `SANDBOX_MODE` | `local` | `local` (in-process execution) or `remote` (external sandboxed execution). |
| `ALLOW_UNSAFE_LOCAL_EXECUTION` | `false` | Run model-written code as an unconfined host subprocess where OS confinement is unavailable. With the default, such code runs only under macOS `sandbox-exec` or Linux `bwrap` (no network, writes only to the run workspace) and is refused elsewhere. Keep disabled for untrusted agent input; see [Sandbox Execution](../guides/production.md#sandbox-execution). |
| `EXECUTION_TIMEOUT` | `300` | Seconds before sandbox code execution is forcibly terminated. |
| `MAX_REPAIR_ATTEMPTS` | `3` | Autonomous repair retries when generated code fails. |
| `HITL_ENABLED` | `false` | Enable Human-in-the-Loop escalation. |
| `HITL_MAX_CONFIDENCE` | `0.8` | Escalate when the Kernel's action confidence is below this value. |
| `HITL_MIN_RISK_SCORE` | `0.7` | Escalate when the evaluated risk score exceeds this value. |
| `HITL_TARGETS` | `reviewer` | Who responds to escalations, comma-separated (e.g. `ops-oncall,finance-approver`). Carried on every request as `targets`; a request can name its own. See [Who responds](../guides/hitl.md#who-responds). |
| `MAX_GOAL_STEPS` | `30` | Hard ceiling on plan steps for goal-oriented agents before the goal is marked `blocked`. |
| `MAX_REPLAN_ATTEMPTS` | `8` | Maximum replanning cycles before the Kernel returns a failure result. |

**Token budgets**

These control how the Kernel allocates context across its OODA turns. You will not need to change these unless you are working with very long tasks or seeing silent truncation.

| Variable | Default | Description |
|---|---|---|
| `KERNEL_MAX_TOTAL_TOKENS` | `80000` | Hard token ceiling per task execution across all Kernel turns. |
| `KERNEL_THINKING_BUDGET` | `56000` | Token allocation for Kernel reasoning turns. |
| `KERNEL_ACTION_BUDGET` | `24000` | Token allocation for action execution turns. |
| `KERNEL_WALL_CLOCK_MS` | `180000` | Maximum wall-clock time in milliseconds for a single task execution (3 minutes). |

**Tool result observation**

Each tool result is shown to the agent whole, once: in the conversation while it
is among the agent's recent exchanges, and in the list of recent actions after
that. Results of the last few turns also stay readable with `read_turn_result`,
a page at a time. Nothing is cut: older results are released whole, and the
agent is told why.

| Variable | Default | Description |
|---|---|---|
| `SUBAGENT_OBSERVATION_LIMIT` | removed | Tool results are no longer clipped; the agent sees each one whole. The setting is ignored. |
| `SUBAGENT_TURN_RESULT_WINDOW` | `10` | Number of recent tool results kept whole for `read_turn_result`. |
| `SUBAGENT_TURN_RESULT_BUDGET` | `2000000` | Total characters kept across those results; older results are released whole when exceeded. |
| `SUBAGENT_READ_PAGE_LIMIT` | `20000` | Largest page `read_turn_result` returns; each page is shown whole. |

---

## Agent Profiles

| Variable | Default | Description |
|---|---|---|
| `JARVISCORE_PROFILES_DIR` | Bundled fallback | Absolute path to your application's agent profile YAML directory |

Set this to your application's profiles directory so that agents load domain-specific role intelligence rather than the bundled example profiles:

```bash title=".env"
JARVISCORE_PROFILES_DIR=/path/to/your-app/profiles/agents
```

---

## Mailbox

The `MailboxManager` is the Redis Streams-backed fire-and-forget messaging layer between agents. These settings only apply when Redis is configured.

| Variable | Default | Description |
|---|---|---|
| `MAILBOX_MAX_MESSAGES` | `100` | Maximum messages drained per `read()` call. |
| `MAILBOX_POLL_INTERVAL` | `0.5` | Seconds between mailbox poll cycles in the listener loop. |

---

## Function Registry

The FunctionRegistry (atom store) promotes generated code through three quality levels: Candidate, Verified, and Golden. These thresholds control when promotion occurs.

| Variable | Default | Description |
|---|---|---|
| `REGISTRY_VERIFIED_THRESHOLD` | `1` | Successful executions before a Candidate atom is promoted to Verified. |
| `REGISTRY_GOLDEN_THRESHOLD` | `5` | Successful executions before a Verified atom is promoted to Golden. Golden atoms are always tried first. |
| `REGISTRY_MAX_CACHE_SIZE` | `500` | Maximum atoms held in the in-memory registry cache. |

See [System Bundles and Atoms](../concepts/system-bundles.md) for a full explanation of the graduation model.

---

## Telemetry

| Variable | Default | Description |
|---|---|---|
| `TELEMETRY_ENABLED` | `true` | Write execution trace files to disk. |
| `TELEMETRY_TRACE_DIR` | `./.jarviscore/traces` | Directory for execution trace files. |
| `PROMETHEUS_ENABLED` | `false` | Start a Prometheus metrics endpoint. |
| `PROMETHEUS_PORT` | `9090` | Port for the `/metrics` endpoint. |

```bash
pip install "jarviscore-framework[prometheus]"
```

---

## Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Log verbosity level: `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
