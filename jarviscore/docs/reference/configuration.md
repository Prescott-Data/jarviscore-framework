---
icon: material/tune
---

# Configuration Reference

This is the complete reference for all JarvisCore environment variables. Copy `.env.example` from your project root after running `jarviscore init`, populate one LLM section, and run `jarviscore check` to validate.

---

## LLM Providers

Configure exactly one LLM provider. JarvisCore auto-detects the active provider from the environment variables present. Multiple providers can be set; the framework tries them in priority order: vLLM → Azure → Gemini → Claude.

=== "Anthropic Claude"

    | Variable | Required | Default | Description |
    |---|---|---|---|
    | `CLAUDE_API_KEY` | Yes | — | API key starting with `sk-ant-` |
    | `CLAUDE_MODEL` | No | `claude-sonnet-4` | Model name |

=== "Google Gemini"

    | Variable | Required | Default | Description |
    |---|---|---|---|
    | `GEMINI_API_KEY` | Yes | — | API key starting with `AIza` |
    | `GEMINI_MODEL` | No | `gemini-2.0-flash` | Model name |

=== "Azure OpenAI"

    | Variable | Required | Default | Description |
    |---|---|---|---|
    | `AZURE_API_KEY` | Yes | — | Azure OpenAI API key |
    | `AZURE_ENDPOINT` | Yes | — | Resource endpoint, e.g. `https://your-resource.openai.azure.com/` |
    | `AZURE_DEPLOYMENT` | Yes | — | Deployment name, e.g. `gpt-4o` |
    | `AZURE_API_VERSION` | No | `2024-02-15-preview` | API version string |

=== "Local / vLLM"

    | Variable | Required | Default | Description |
    |---|---|---|---|
    | `LLM_ENDPOINT` | Yes | — | OpenAI-compatible endpoint URL |
    | `LLM_MODEL` | Yes | — | Model name as expected by the endpoint |

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
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature for all providers. |
| `LLM_MAX_CONCURRENT` | `0` | Maximum concurrent LLM calls across the whole process. `0` means unlimited. Set to approximately `RPM ÷ avg_latency_seconds` to avoid 429 storms in multi-agent deployments. |
| `LLM_MAX_RETRIES_429` | `4` | Retry attempts when a provider returns 429 before giving up. |
| `LLM_429_BASE_DELAY` | `2.0` | Exponential backoff base delay in seconds. Actual delay: `min(base × 2^attempt, 60s)`. |
| `AZURE_CONTENT_FILTER_REPAIR_ENABLED` | `false` | Opt into an Azure-specific content-filter retry that applies a provider-safe preamble and neutral wording after the raw prompt is rejected. Off by default so prompt rewriting never hides developer intent. |

---

## Redis

Without Redis, JarvisCore runs in in-process mode: workflows execute locally, mailboxes are file-backed, and distributed features are unavailable. With Redis, the following capabilities become active: distributed workflow DAGs, durable mailboxes, cross-node step claiming, episodic ledger, and LTM compression.

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | — | Full connection URL; takes precedence over host/port variables. Example: `redis://host:6379/0` |
| `REDIS_HOST` | `localhost` | Used when `REDIS_URL` is not set |
| `REDIS_PORT` | `6379` | Used when `REDIS_URL` is not set |
| `REDIS_PASSWORD` | — | Authentication password |
| `REDIS_DB` | `0` | Database number |
| `REDIS_CONTEXT_TTL_DAYS` | `7` | Number of days to retain agent context keys |

Start Redis locally for development:

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

---

## Memory: Athena MemOS

Athena provides three-tier persistent memory (STM, MTM, and LTM graph) that spans sessions. Without Athena, agents use Redis-only episodic memory for the current session.

| Variable | Default | Description |
|---|---|---|
| `ATHENA_URL` | — | Athena API base URL, e.g. `http://localhost:8080` |
| `ATHENA_TENANT_ID` | `default` | Tenant namespace for memory isolation across teams or environments |
| `ATHENA_HTTP_TIMEOUT` | `10.0` | Seconds before an Athena HTTP call times out. Increase if your Athena instance is remote or under load. |
| `ATHENA_SESSION_TTL_DAYS` | `30` | How long a session ID is cached in Redis before Athena re-issues it. |

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
| `STORAGE_BACKEND` | `local` | `local` or `azure` |
| `STORAGE_BASE_PATH` | `./blob_storage` | Base directory path for the local backend |
| `AZURE_STORAGE_CONNECTION_STRING` | — | Required when `STORAGE_BACKEND=azure` |

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

JarvisCore runs multiple search providers in parallel and merges results. All providers have circuit breakers — a failing provider is skipped automatically. See the [Internet Search guide](../guides/internet-search.md) for provider details, ranking logic, and usage patterns.

### Google Grounded Search <span class="jc-badge jc-badge-primary">Primary</span>

Active automatically when `GEMINI_API_KEY` is set (which is already required for agents). No extra configuration needed.

| Variable | Default | Description |
|---|---|---|
| `GEMINI_GROUNDING_API_KEY` | `GEMINI_API_KEY` | Override the key used specifically for grounded search |
| `GEMINI_GROUNDING_MODEL` | `gemini-2.5-flash` | Gemini model used for grounded search |
| `GOOGLE_CLOUD_PROJECT` | — | Vertex AI path (alternative to API key) |
| `GOOGLE_CLOUD_LOCATION` | `global` | GCP location for Vertex AI |

### Serper <span class="jc-badge jc-badge-optional">Optional</span>

| Variable | Default | Description |
|---|---|---|
| `SERPER_API_KEY` | — | API key from [serper.dev](https://serper.dev). Provider is skipped if unset. |

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

---

## Nexus: Credential Management

Required only when agents call third-party services (GitHub, Slack, Jira, Stripe, and so on) through providers registered with `requires_auth = True`.

| Variable | Default | Description |
|---|---|---|
| `NEXUS_GATEWAY_URL` | — | Gateway URL, e.g. `http://localhost:8090` |
| `NEXUS_BROKER_URL` | — | Broker URL, e.g. `http://localhost:8080`. Used by dashboard and SDK to POST credentials directly to the Broker's `/auth/capture-credential` endpoint for non-OAuth providers. |
| `NEXUS_RETURN_URL` | `http://localhost:8000/oauth/callback` | OAuth callback URL; the Nexus broker redirects here after consent. |
| `NEXUS_DEFAULT_USER_ID` | `jarviscore-agent` | User identity passed to Nexus for credential lookups. |
| `AUTH_STRATEGY_CACHE_TTL` | `300` | Seconds before the resolved auth strategy is re-fetched from the Gateway. |
| `AUTH_FLOW_TIMEOUT` | `300` | Maximum seconds to wait for a user to complete OAuth browser consent. |
| `AUTH_POLL_INTERVAL` | `2.0` | Seconds between Gateway status polls during an OAuth flow. |
| `AUTH_OPEN_BROWSER` | `true` | Whether to open the system browser automatically when OAuth consent is needed. |

Initial setup:

```bash
jarviscore nexus init
jarviscore nexus register github \
    --client-id=YOUR_ID \
    --client-secret=YOUR_SECRET
jarviscore nexus test github
```

---

## P2P / SWIM Mesh

Enables multi-node agent discovery and message routing using the SWIM gossip protocol and ZMQ transport. Requires Redis for distributed workflow coordination.

| Variable | Default | Description |
|---|---|---|
| `P2P_ENABLED` | `false` | Activates the SWIM coordinator and ZMQ transport |
| `JC_SWIM_HOST` | `0.0.0.0` | Bind address; `0.0.0.0` listens on all interfaces |
| `JC_SWIM_PORT` | `7946` | SWIM gossip port; must be unique per node on the same machine |
| `JC_SEED_NODES` | — | Comma-separated list of seed node addresses, e.g. `10.0.0.1:7946,10.0.0.2:7946` |

!!! warning "Port uniqueness"
    `JC_SWIM_PORT` must be different for each node running on the same machine. The ZMQ data port is set automatically to `JC_SWIM_PORT + 1000`.

The seed node does not set `JC_SEED_NODES`. All other nodes point at the seed node (or any other live node) to join the cluster.

---

## Kernel Tuning

Advanced execution parameters for the OODA loop Kernel. The defaults are appropriate for the majority of workloads.

**Execution limits**

| Variable | Default | Description |
|---|---|---|
| `KERNEL_MAX_TURNS` | `30` | Maximum OODA loop turns per task execution. |
| `SANDBOX_MODE` | `local` | `local` (in-process execution) or `remote` (external sandboxed execution). |
| `EXECUTION_TIMEOUT` | `300` | Seconds before sandbox code execution is forcibly terminated. |
| `MAX_REPAIR_ATTEMPTS` | `3` | Autonomous repair retries when generated code fails. |
| `HITL_ENABLED` | `false` | Enable Human-in-the-Loop escalation. |
| `HITL_MAX_CONFIDENCE` | `0.8` | Escalate when the Kernel's action confidence is below this value. |
| `HITL_MIN_RISK_SCORE` | `0.7` | Escalate when the evaluated risk score exceeds this value. |
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
| `TELEMETRY_TRACE_DIR` | `./traces` | Directory for execution trace files. |
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
