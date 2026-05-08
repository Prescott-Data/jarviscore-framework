---
icon: material/rocket-launch
---

# Production Deployment

This guide covers what changes when you move JarvisCore from a local development setup to a production environment. Every configuration value, behaviour, and constraint documented here is sourced from the framework's actual settings model and runtime code.

> [!IMPORTANT]
> This guide assumes you have a working local agent. If you have not completed [Getting Started](../getting-started.md) first, start there.

---

## What Actually Changes in Production

| Concern | Development | Production |
|---|---|---|
| Sandbox execution | `SANDBOX_MODE=local` (in-process `exec()`) | `SANDBOX_MODE=remote` (isolated HTTP service) |
| Nexus credentials | `~/.jarviscore/nexus.enc` keyed to machine UUID | `NEXUS_GATEWAY_URL` pointing to a deployed gateway |
| `NEXUS_SECRET` | Falls back to machine UUID and prints a warning | Must be set to a long random secret |
| Redis | Optional, connects to localhost | Required for state persistence, mailbox, and crash recovery |
| Blob storage | `STORAGE_BACKEND=local` writes to local filesystem | `STORAGE_BACKEND=azure` or a mounted persistent volume |
| Athena memory | Optional | Required for cross-session memory via `ATHENA_URL` |
| Prometheus | Off by default | Enabled with `PROMETHEUS_ENABLED=true` |
| LLM concurrency | Unlimited | Set `LLM_MAX_CONCURRENT` to match your provider's RPM |
| P2P bind host | `127.0.0.1` | `0.0.0.0` to be reachable by other nodes |
| Log level | `DEBUG` or `INFO` | `INFO` or `WARNING` |

---

## Production Checklist

Before deploying, confirm each item:

- [ ] At least one LLM provider is configured (`AZURE_API_KEY`, `CLAUDE_API_KEY`, or `GEMINI_API_KEY`)
- [ ] `NEXUS_SECRET` is set to a long random string and not left to the machine UUID fallback
- [ ] `NEXUS_GATEWAY_URL` points to your deployed Nexus Gateway and not to `localhost`
- [ ] `REDIS_URL` is set to an external Redis instance with persistence enabled
- [ ] `STORAGE_BACKEND` is set to `azure` or points to a volume-backed path
- [ ] `SANDBOX_MODE=remote` and `SANDBOX_SERVICE_URL` are configured if you require isolated execution
- [ ] `PROMETHEUS_ENABLED=true` and your scrape target is registered
- [ ] `LLM_MAX_CONCURRENT` is set to prevent cascading 429 errors
- [ ] `LOG_LEVEL=INFO` is set to avoid token content appearing in logs
- [ ] `P2P_ENABLED` and per-node bind ports are configured correctly for multi-node deployments
- [ ] `EXECUTION_TIMEOUT` is tuned for your expected task durations

---

## Environment and Secrets

The framework loads configuration from a `.env` file and from environment variables. In production, do not use `.env` files. Inject secrets via your platform's secret management instead.

### Required for any agent

At minimum, one LLM provider must be configured:

```bash
# Azure OpenAI
AZURE_API_KEY=...
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o
AZURE_API_VERSION=2025-01-01-preview

# Anthropic Claude
CLAUDE_API_KEY=...

# Google Gemini
GEMINI_API_KEY=...
```

### LLM rate limiting

In a multi-agent deployment, agents generate concurrent LLM calls. Without a concurrency cap, all agents will hit provider 429 rate limits simultaneously. Set `LLM_MAX_CONCURRENT` using this formula: divide your provider's requests-per-minute limit by the expected average call latency in seconds.

```bash
# Example: RPM=60, average latency=5s → 60 ÷ 12 = 5
LLM_MAX_CONCURRENT=5

# 429 retry backoff: 4 retries with exponential delay, starting at 2s, capped at 60s
LLM_MAX_RETRIES_429=4
LLM_429_BASE_DELAY=2.0
```

### Model routing

Two-tier routing works with any configured provider:

```bash
CODING_MODEL=gpt-4.1    # Used by CoderSubAgent for code generation
TASK_MODEL=gpt-4o       # Used by Researcher, Communicator, and Browser agents
```

Three-tier routing is optional. Enable it by passing `complexity=` in workflow task dicts:

```bash
TASK_MODEL_NANO=gpt-4o-mini    # For fast, inexpensive tasks: classify, summarise, route
TASK_MODEL_STANDARD=gpt-4o     # For general tasks
TASK_MODEL_HEAVY=o3             # For deep reasoning, long context, and planning
```

---

## Nexus Gateway in Production

In local development, Nexus uses `~/.jarviscore/nexus.enc`, a file encrypted with a key derived from the machine's hardware UUID. In production, this approach has three problems.

First, the local file is single-machine only. Credentials stored on one machine cannot be decrypted on another. Second, the machine UUID fallback is not suitable for containers, because container restarts may produce different UUIDs. Third, multiple agent nodes cannot share credentials from a local file.

The production path is the Nexus Gateway.

### Deploy the Nexus stack

The Nexus Gateway is an open-source service. Clone the repository and deploy it:

```bash
git clone https://github.com/Prescott-Data/nexus-framework
```

Or use the bundled Docker Compose file for initial setup:

```bash
jarviscore nexus init
```

This command generates `NEXUS_ENCRYPTION_KEY` and `NEXUS_STATE_KEY`, writes them to `.env`, and starts the stack. For production, extract these values and store them in your platform's secret manager before they reach version control.

### Nexus Gateway architecture

The stack has three components:

| Component | Port | Role |
|---|---|---|
| Broker | 8080 | Handles OAuth callbacks and stores encrypted tokens in Postgres |
| Gateway | 8090 | The control plane that JarvisCore communicates with |
| Postgres | 5432 | Broker persistence |

The Gateway always dials the Broker at `localhost:8080` within the same network namespace. In the provided Docker Compose configuration, the Gateway runs with `network_mode: service:nexus-broker` so that `localhost` resolves to the Broker container correctly.

### Required environment variables for Gateway mode

```bash
NEXUS_GATEWAY_URL=https://your-nexus-gateway.internal:8090
NEXUS_RETURN_URL=https://your-app.com/oauth/callback   # OAuth redirect target after consent
NEXUS_SECRET=<long-random-secret>                       # Key derivation for local store fallback
NEXUS_ENCRYPTION_KEY=<openssl rand -base64 32>          # Gateway token encryption key
NEXUS_STATE_KEY=<openssl rand -base64 32>               # OAuth state parameter for CSRF protection
```

> [!CAUTION]
> If `NEXUS_SECRET` is not set, the local credential store falls back to machine UUID for key derivation and logs a warning. In a containerised environment this is unreliable. Always set `NEXUS_SECRET`.

### Credential strategy cache

Agents cache resolved auth strategies locally to avoid calling the Gateway on every request. The default cache duration is 300 seconds. Lower this value if your credentials rotate frequently.

```bash
AUTH_STRATEGY_CACHE_TTL=300
```

---

## Redis

Redis is optional in development. In production it serves as the backbone for cross-step state, agent-to-agent messaging via the mailbox, episodic memory events, crash recovery, and the HITL queue.

```bash
# A full connection string takes precedence over component settings
REDIS_URL=redis://:your-password@redis.internal:6379/0

# Alternatively, set individual components
REDIS_HOST=redis.internal
REDIS_PORT=6379
REDIS_PASSWORD=your-password
REDIS_DB=0

# How long agent context is retained (default: 7 days)
REDIS_CONTEXT_TTL_DAYS=7
```

Install the Redis extra:

```bash
pip install "jarviscore-framework[redis]"
```

Use a Redis instance with persistence enabled. The bundled `docker-compose.infra.yml` enables this with the `appendonly yes` flag:

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes
  volumes:
    - redis_data:/data
```

---

## Blob Storage

The framework uses blob storage for atom versioning, function registry persistence, and long-term memory artifacts.

### Local filesystem (development default)

```bash
STORAGE_BACKEND=local
STORAGE_BASE_PATH=./blob_storage
```

This writes to the local filesystem. In a containerised deployment, this data is lost on restart unless you mount a persistent volume at `STORAGE_BASE_PATH`.

### Azure Blob Storage (production)

```bash
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...
AZURE_STORAGE_CONTAINER=jarviscore   # The container is created automatically if it does not exist
```

Install the Azure extra:

```bash
pip install "jarviscore-framework[azure]"
```

---

## Athena Memory

Athena is the framework's Tier 3 and Tier 4 memory layer. It provides structured episodic knowledge and a graph-based relational store. Without `ATHENA_URL`, agents use Redis-only episodic memory (Tiers 1 and 2). Setting `ATHENA_URL` upgrades all agents to full three-tier memory automatically, with no code changes required.

```bash
ATHENA_URL=http://athena.internal:8080

ATHENA_TENANT_ID=default      # Namespace for multi-tenant Athena deployments
ATHENA_HTTP_TIMEOUT=10.0      # Seconds before an Athena HTTP call times out
ATHENA_SESSION_TTL_DAYS=30    # How long the session_id is cached in Redis
```

Set up the Athena stack:

```bash
git clone https://github.com/Prescott-Data/athena ~/athena
jarviscore memory init
```

Install the memory extra:

```bash
pip install "jarviscore-framework[memory-athena]"
```

---

## Sandbox Execution

The sandbox is how JarvisCore executes generated code. There are two modes.

### Local mode (default)

In local mode, `exec()` runs in the same Python process as the agent. This is fast with zero overhead. It is appropriate for development and for low-risk deployments where you trust the agent's code generation output.

```bash
SANDBOX_MODE=local
EXECUTION_TIMEOUT=300    # Seconds before a code block is killed
MAX_REPAIR_ATTEMPTS=3    # How many times the Kernel retries failed code before giving up
```

### Remote mode (isolated)

In remote mode, generated code is sent as an HTTP POST to an external sandbox service. The agent process is fully isolated from the executing code. The sandbox can be hardened, resource-capped, and run in a separate security boundary.

```bash
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://your-sandbox-service.internal/execute
```

> [!NOTE]
> If `SANDBOX_MODE=remote` is set but `SANDBOX_SERVICE_URL` is missing or unreachable, the framework logs a warning and falls back to local mode rather than crashing.

---

## Observability

### Prometheus metrics

Prometheus metrics are exposed by the Mesh layer when `PROMETHEUS_ENABLED=true`. The metrics server starts on the configured port when the first agent connects to the mesh.

```bash
PROMETHEUS_ENABLED=true
PROMETHEUS_PORT=9090
```

Install the Prometheus extra:

```bash
pip install "jarviscore-framework[prometheus]"
```

The bundled `docker-compose.infra.yml` includes a Prometheus and Grafana stack. Prometheus is configured to scrape `host.docker.internal:9090` by default. Adjust `prometheus.yml` if your agent runs on a different host or port.

### Trace files

The framework writes structured trace files regardless of whether Prometheus is enabled:

```bash
TELEMETRY_ENABLED=true          # Enabled by default
TELEMETRY_TRACE_DIR=./traces    # Directory for trace JSON files
```

In production, mount `TELEMETRY_TRACE_DIR` to a persistent volume or configure your observability platform to ship traces from this directory.

### Log level

```bash
LOG_LEVEL=INFO
```

Set the log level to `INFO` in production. The `DEBUG` level exposes LLM payloads in logs, which may contain sensitive context.

---

## Running Agents

### Docker

A minimal Dockerfile for a JarvisCore agent:

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "my_agent.py"]
```

Inject all secrets via environment variables at runtime. Never bake API keys or credentials into the image.

### Persistent volumes

Mount the following paths to persistent storage to survive container restarts:

| Path | Purpose |
|---|---|
| `STORAGE_BASE_PATH` (default `./blob_storage`) | Atom registry and LTM artifacts |
| `TELEMETRY_TRACE_DIR` (default `./traces`) | Trace files |
| `LOG_DIRECTORY` (default `./logs`) | Log files |
| `~/.jarviscore/` | Nexus local store, only required when not using Gateway mode |

### Process supervision

For non-containerised deployments, use a process supervisor to keep agents running across failures and reboots:

```ini
# /etc/systemd/system/my-agent.service
[Unit]
Description=JarvisCore Agent — my-agent
After=network.target redis.service

[Service]
Type=simple
User=jarviscore
WorkingDirectory=/opt/my-agent
EnvironmentFile=/opt/my-agent/.env
ExecStart=/opt/my-agent/venv/bin/python my_agent.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Scaling to a Fleet (P2P)

JarvisCore's P2P layer uses a SWIM-based gossip protocol for peer discovery and a ZeroMQ transport for agent-to-agent messaging. Each node in a fleet is a separate process with a unique bind port.

### Per-node configuration

Bind port and bind host are per-process settings. They cannot be set once in a shared `.env` file because every node needs a different port. Set them at process launch:

```bash
# Node 1 — the seed node that other nodes join through
JARVISCORE_BIND_HOST=0.0.0.0 \
JARVISCORE_BIND_PORT=7946 \
JARVISCORE_NODE_NAME=researcher-01 \
python researcher.py

# Node 2 — joins the cluster through the seed node
JARVISCORE_BIND_HOST=0.0.0.0 \
JARVISCORE_BIND_PORT=7947 \
JARVISCORE_NODE_NAME=coder-01 \
JARVISCORE_SEED_NODES=192.168.1.10:7946 \
python coder.py
```

You can also configure these values in code to avoid environment variable collisions:

```python
from jarviscore import Mesh

mesh = Mesh(config={
    "p2p_enabled": True,
    "bind_host": "0.0.0.0",
    "bind_port": 7947,
    "seed_nodes": "192.168.1.10:7946",
})
```

### Shared settings for fleets

These settings are safe to share across all nodes in a `.env` file or secret store:

```bash
P2P_ENABLED=true
TRANSPORT_TYPE=hybrid       # Accepted values: udp, tcp, hybrid. Hybrid is the default.
ZMQ_PORT_OFFSET=1000        # ZeroMQ port is calculated as bind_port + this offset

KEEPALIVE_ENABLED=true
KEEPALIVE_INTERVAL=90       # Seconds between keepalive pings
KEEPALIVE_TIMEOUT=10        # Seconds before a peer is considered unreachable
ACTIVITY_SUPPRESS_WINDOW=60 # Keepalive is suppressed when an agent is active within this window
```

### Firewall requirements

Each node requires the following ports to be open to other fleet members:

| Port | Protocol | Purpose |
|---|---|---|
| `JARVISCORE_BIND_PORT` (default 7946) | UDP and TCP | SWIM gossip for peer discovery |
| `JARVISCORE_BIND_PORT + ZMQ_PORT_OFFSET` (default 8946) | TCP | ZeroMQ agent-to-agent messaging |

---

## Cloud Deployments

JarvisCore has no cloud-specific dependencies. The same pattern applies on every platform: deploy agents as containers, replace local development infrastructure with managed equivalents, and inject secrets from the platform's secret manager.

### AWS

| JarvisCore dependency | AWS managed equivalent |
|---|---|
| Redis | ElastiCache for Redis with persistence enabled |
| Blob storage | S3 with a FUSE adapter, or local mode on EFS |
| Nexus Gateway | ECS (Fargate) or EKS |
| Agents | ECS (Fargate) or EKS |
| Secrets | AWS Secrets Manager or Systems Manager Parameter Store |
| Athena | EC2 or EKS with persistent volumes |

Inject secrets at container startup using the AWS CLI:

```bash
export AZURE_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id prod/jarviscore/azure-api-key \
  --query SecretString --output text)
```

For P2P fleets on ECS or EKS, each task or pod needs a unique `JARVISCORE_BIND_PORT` and must be able to reach other nodes on both the SWIM and ZMQ ports. Use a service mesh such as AWS App Mesh or direct VPC networking. Do not route P2P traffic through a load balancer.

### Azure

| JarvisCore dependency | Azure managed equivalent |
|---|---|
| Redis | Azure Cache for Redis with RDB and AOF persistence enabled |
| Blob storage | Azure Blob Storage using `STORAGE_BACKEND=azure` and `AZURE_STORAGE_CONNECTION_STRING` |
| Nexus Gateway | Azure Container Apps or AKS |
| Agents | Azure Container Apps or AKS |
| Secrets | Azure Key Vault via Key Vault references or Managed Identity |
| Athena | AKS with persistent volumes using Azure Disk or Azure Files |

Azure Blob Storage is the native backend and requires no adapter:

```bash
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_STORAGE_CONTAINER=jarviscore
```

Use Managed Identity rather than connection strings where possible. Assign the `Storage Blob Data Contributor` role to the agent's Managed Identity.

### GCP

| JarvisCore dependency | GCP managed equivalent |
|---|---|
| Redis | Memorystore for Redis with persistence enabled |
| Blob storage | Cloud Storage with a FUSE adapter, or local mode on a Filestore volume |
| Nexus Gateway | Cloud Run or GKE |
| Agents | Cloud Run or GKE |
| Secrets | Secret Manager via Cloud Run secret references or Workload Identity |
| Athena | GKE with persistent volumes using Persistent Disk |

Inject secrets on Cloud Run:

```yaml
# cloud-run-service.yaml (excerpt)
env:
  - name: AZURE_API_KEY
    valueFrom:
      secretKeyRef:
        name: jarviscore-azure-api-key
        version: latest
```

---

## Kernel Limits

The Kernel enforces hard limits on agent reasoning loops. Review these defaults and tune them for your workload:

```bash
# Maximum OODA loop iterations per task (default: 30)
KERNEL_MAX_TURNS=30

# Maximum total tokens across a task (default: 80,000)
KERNEL_MAX_TOTAL_TOKENS=80000

# Wall-clock time limit per task in milliseconds (default: 180,000, which is 3 minutes)
KERNEL_WALL_CLOCK_MS=180000

# Token budget allocated within a single turn
KERNEL_THINKING_BUDGET=56000
KERNEL_ACTION_BUDGET=24000
```

For long-running research tasks, increase `KERNEL_MAX_TURNS` and `KERNEL_WALL_CLOCK_MS`. For cost-sensitive deployments, reduce them. A task that exceeds any of these limits returns a timeout result. It does not crash the agent process.

---

## Security Checklist

**Never bake secrets into Docker images.** All credentials must be injected at runtime via environment variables.

**Set `NEXUS_SECRET`.** The machine UUID fallback logs a warning and produces unreliable key derivation in containerised environments.

**Use `SANDBOX_MODE=remote`** if agents process untrusted input or if generated code must be isolated from the agent process.

**Set `LOG_LEVEL=INFO`.** The `DEBUG` level includes LLM payloads in logs, which may contain sensitive task context.

**Tune `EXECUTION_TIMEOUT`.** The default of 300 seconds is deliberately conservative. Set it to match your expected task durations.

**Restrict P2P ports to internal traffic.** The SWIM and ZMQ ports must be reachable within the fleet but must not be exposed to the public internet.

**Enable `HITL_ENABLED=true` for high-risk agents.** The HITL queue requires explicit human approval before the agent executes flagged actions.
