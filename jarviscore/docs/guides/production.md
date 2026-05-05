---
icon: material/rocket-launch
---

# Production Deployment

This guide covers what changes when you move JarvisCore from a local development setup to a production environment. Every configuration value, behaviour, and constraint documented here is sourced from the framework's actual settings model and runtime code.

> [!IMPORTANT]
> This guide assumes you have a working local agent. If you haven't completed [Getting Started](../getting-started.md) first, start there.

---

## What Actually Changes in Production

| Concern | Development | Production |
|---|---|---|
| Sandbox execution | `SANDBOX_MODE=local` (in-process `exec()`) | `SANDBOX_MODE=remote` (isolated HTTP service) |
| Nexus credentials | `~/.jarviscore/nexus.enc` keyed to machine UUID | `NEXUS_GATEWAY_URL` pointing to a deployed gateway |
| `NEXUS_SECRET` | Falls back to machine UUID — **prints a warning** | Must be set — a long random secret |
| Redis | Optional, localhost | Required for state persistence, mailbox, crash recovery |
| Blob storage | `STORAGE_BACKEND=local` (local filesystem) | `STORAGE_BACKEND=azure` or a mounted persistent volume |
| Athena memory | Optional | Required for cross-session memory (`ATHENA_URL`) |
| Prometheus | Off by default | `PROMETHEUS_ENABLED=true`, `PROMETHEUS_PORT=9090` |
| LLM concurrency | Unlimited | Set `LLM_MAX_CONCURRENT` to match your provider's RPM |
| P2P bind host | `127.0.0.1` | `0.0.0.0` — exposed to the network |
| Log level | `DEBUG` or `INFO` | `INFO` or `WARNING` |

---

## Production Checklist

Before deploying, confirm each item:

- [ ] At least one LLM provider is configured (`AZURE_API_KEY`, `CLAUDE_API_KEY`, or `GEMINI_API_KEY`)
- [ ] `NEXUS_SECRET` is set to a long random string (not left to machine UUID fallback)
- [ ] `NEXUS_GATEWAY_URL` points to your deployed Nexus Gateway (not `localhost`)
- [ ] `REDIS_URL` is set to an external Redis instance with persistence
- [ ] `STORAGE_BACKEND` is set to `azure` or a volume-backed path
- [ ] `SANDBOX_MODE=remote` and `SANDBOX_SERVICE_URL` are configured if you require isolated execution
- [ ] `PROMETHEUS_ENABLED=true` and your scrape target is registered
- [ ] `LLM_MAX_CONCURRENT` is set to prevent 429 thundering-herd errors
- [ ] `LOG_LEVEL=INFO` (not `DEBUG`) to avoid token content in logs
- [ ] `P2P_ENABLED` and per-node bind ports are set correctly for multi-node deployments
- [ ] `EXECUTION_TIMEOUT` is tuned for your expected task durations

---

## Environment & Secrets

The framework loads configuration from a `.env` file and environment variables. In production, **do not use `.env` files** — inject secrets via your platform's secret management.

### Required for any agent

```bash
# At minimum ONE of these LLM providers must be set
AZURE_API_KEY=...
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o
AZURE_API_VERSION=2025-01-01-preview

# Or Claude
CLAUDE_API_KEY=...

# Or Gemini
GEMINI_API_KEY=...
```

### LLM rate limiting — critical for multi-agent fleets

In a multi-agent deployment, agents generate concurrent LLM calls. Without a concurrency cap, you will hit provider 429s simultaneously across all agents:

```bash
# Set to: (provider RPM ÷ expected average call latency in seconds)
# Example: RPM=60, avg latency=5s → 60÷12 = 5
LLM_MAX_CONCURRENT=5

# 429 retry backoff — default is 4 retries with exponential delay (2s base, max 60s)
LLM_MAX_RETRIES_429=4
LLM_429_BASE_DELAY=2.0
```

### Model routing

Two-tier routing (always works with any configured provider):

```bash
CODING_MODEL=gpt-4.1          # CoderSubAgent — code generation
TASK_MODEL=gpt-4o             # Researcher, Communicator, Browser
```

Optional three-tier routing (pass `complexity=` in workflow task dicts):

```bash
TASK_MODEL_NANO=gpt-4o-mini   # Fast/cheap: classify, summarise, route
TASK_MODEL_STANDARD=gpt-4o    # General tasks
TASK_MODEL_HEAVY=o3            # Deep reasoning, long context, planning
```

---

## Nexus Gateway in Production

In local development, Nexus uses `~/.jarviscore/nexus.enc` — a file encrypted with a key derived from the machine's hardware UUID. In production:

1. The local file is **single-machine only** — credentials on one machine cannot be decrypted on another
2. The machine UUID fallback is **not suitable for containers** — container restarts may produce different UUIDs
3. Multiple agent nodes cannot share credentials from a local file

**The production path is the Nexus Gateway.**

### Deploy the Nexus stack

The Nexus Gateway is an open-source service. Clone and deploy it:

```bash
# The Nexus Gateway repository
git clone https://github.com/Prescott-Data/nexus-framework
```

Or use the bundled Docker Compose file for the initial setup:

```bash
jarviscore nexus init
```

This generates `NEXUS_ENCRYPTION_KEY` and `NEXUS_STATE_KEY`, writes them to `.env`, and starts the stack. For production, extract these values and store them in your platform's secret manager.

### Nexus Gateway architecture

The stack has three components:

| Component | Port | Role |
|---|---|---|
| Broker | 8080 | Handles OAuth callbacks, stores encrypted tokens in Postgres |
| Gateway | 8090 | Control plane — what JarvisCore talks to |
| Postgres | 5432 | Broker persistence |

The Gateway always dials the Broker at `localhost:8080` in the same network namespace. In the provided Docker Compose configuration, the Gateway runs with `network_mode: service:nexus-broker` so that `localhost` resolves correctly.

### Required environment variables for Gateway mode

```bash
NEXUS_GATEWAY_URL=https://your-nexus-gateway.internal:8090
NEXUS_RETURN_URL=https://your-app.com/oauth/callback   # OAuth redirect target
NEXUS_SECRET=<long-random-secret>                       # Key derivation for local store fallback
NEXUS_ENCRYPTION_KEY=<openssl rand -base64 32>          # Gateway token encryption
NEXUS_STATE_KEY=<openssl rand -base64 32>               # OAuth state CSRF protection
```

> [!CAUTION]
> If `NEXUS_SECRET` is not set, the local credential store falls back to machine UUID for key derivation and logs a warning. In a containerised environment this is unreliable. Always set `NEXUS_SECRET`.

### Credential strategy cache

```bash
# Seconds before re-fetching auth strategy from Gateway (default: 300)
AUTH_STRATEGY_CACHE_TTL=300
```

Agents cache resolved auth strategies locally. In production you may want to lower this if credentials rotate frequently.

---

## Redis — State Persistence

Redis is optional in development. In production it is the backbone for:

- **Cross-step state** — context store survives between agent turns
- **Mailbox** — peer-to-peer message passing between agents in a fleet
- **Episodic ledger** — short-term and mid-term memory events
- **Crash recovery** — agents can resume incomplete tasks after restart
- **HITL queue** — human-in-the-loop requests persist across restarts

```bash
# Full connection string takes precedence
REDIS_URL=redis://:your-password@redis.internal:6379/0

# Or component parts
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

Use a Redis instance with **persistence enabled** (`appendonly yes`). The bundled `docker-compose.infra.yml` configures this:

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

### Local (development default)

```bash
STORAGE_BACKEND=local
STORAGE_BASE_PATH=./blob_storage
```

This writes to the local filesystem. In a containerised deployment this data is lost on restart unless you mount a persistent volume at `STORAGE_BASE_PATH`.

### Azure Blob Storage (production)

```bash
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...
AZURE_STORAGE_CONTAINER=jarviscore      # Container is created automatically if it doesn't exist
```

Install the Azure extra:

```bash
pip install "jarviscore-framework[azure]"
```

---

## Athena Memory

Athena is the framework's Tier 3 and Tier 4 memory layer — structured episodic knowledge and a graph-based relational store. Without `ATHENA_URL`, agents use Redis-only episodic memory (Tier 1–2). Setting `ATHENA_URL` upgrades all agents to full three-tier memory automatically with no code changes.

```bash
ATHENA_URL=http://athena.internal:8080

# Optional tuning
ATHENA_TENANT_ID=default              # Namespace for multi-tenant deployments
ATHENA_HTTP_TIMEOUT=10.0              # Seconds before Athena HTTP call times out
ATHENA_SESSION_TTL_DAYS=30            # How long session_id is cached in Redis
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

The sandbox is how JarvisCore executes generated code. Two modes:

### Local mode (default)

`exec()` runs in the same Python process as the agent. Fast, zero overhead — correct for development and low-risk deployments where you trust the agent's code generation.

```bash
SANDBOX_MODE=local
EXECUTION_TIMEOUT=300    # Seconds before a code block is killed
MAX_REPAIR_ATTEMPTS=3    # How many times the Kernel retries failed code
```

### Remote mode (isolated)

Sends generated code as an HTTP POST to an external sandbox service. The agent process is fully isolated from the executing code — the sandbox can be hardened, resource-capped, and run in a separate security boundary.

```bash
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://your-sandbox-service.internal/execute
```

> [!NOTE]
> If `SANDBOX_MODE=remote` is set but `SANDBOX_SERVICE_URL` is missing, the framework logs a warning and falls back to `local` mode rather than crashing.

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

The bundled `docker-compose.infra.yml` includes a Prometheus + Grafana stack. Prometheus scrapes `host.docker.internal:9090` by default — adjust `prometheus.yml` if your agent runs on a different host or port.

### Trace files

The framework writes structured trace files regardless of Prometheus:

```bash
TELEMETRY_ENABLED=true           # Default: true
TELEMETRY_TRACE_DIR=./traces     # Directory for trace JSON files
```

In production, mount `TELEMETRY_TRACE_DIR` to a persistent volume or ship traces to your observability platform.

### Log level

```bash
LOG_LEVEL=INFO    # INFO in production — DEBUG exposes token content in logs
```

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

# Secrets are injected at runtime — never baked into the image
CMD ["python", "my_agent.py"]
```

All secrets are injected via environment variables at runtime — never bake API keys into the image.

### Persistent volumes

Mount the following paths to persistent storage to survive container restarts:

| Path | Purpose |
|---|---|
| `STORAGE_BASE_PATH` (default `./blob_storage`) | Atom registry, LTM artifacts |
| `TELEMETRY_TRACE_DIR` (default `./traces`) | Trace files |
| `LOG_DIRECTORY` (default `./logs`) | Log files |
| `~/.jarviscore/` | Nexus local store (only if not using Gateway mode) |

### Process supervision

For non-containerised deployments, use a process supervisor to keep agents running:

```ini
# systemd unit example — /etc/systemd/system/my-agent.service
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

Bind port and host are **per-process settings** — they cannot be set once in a shared `.env` because every node needs a different port. Set them at process launch:

```bash
# Node 1 — seed node
JARVISCORE_BIND_HOST=0.0.0.0 \
JARVISCORE_BIND_PORT=7946 \
JARVISCORE_NODE_NAME=researcher-01 \
python researcher.py

# Node 2 — joins via seed
JARVISCORE_BIND_HOST=0.0.0.0 \
JARVISCORE_BIND_PORT=7947 \
JARVISCORE_NODE_NAME=coder-01 \
JARVISCORE_SEED_NODES=192.168.1.10:7946 \
python coder.py
```

Or configure in code to avoid environment variable collisions:

```python
from jarviscore import Mesh

mesh = Mesh(
    mode="distributed",
    config={
        "bind_host": "0.0.0.0",
        "bind_port": 7947,
        "seed_nodes": "192.168.1.10:7946",
    }
)
```

### Shared `.env` settings for fleets

These are safe to share across all nodes:

```bash
P2P_ENABLED=true
TRANSPORT_TYPE=hybrid          # udp, tcp, or hybrid — hybrid is the default
ZMQ_PORT_OFFSET=1000           # ZeroMQ port = bind_port + offset

# Keepalive — suppressed automatically when agents are actively working
KEEPALIVE_ENABLED=true
KEEPALIVE_INTERVAL=90          # Seconds between keepalive pings
KEEPALIVE_TIMEOUT=10           # Seconds before a peer is considered lost
ACTIVITY_SUPPRESS_WINDOW=60    # Suppress keepalive when active within this window
```

### Firewall requirements

Each node needs the following ports open between fleet members:

| Port | Protocol | Purpose |
|---|---|---|
| `JARVISCORE_BIND_PORT` (default 7946) | UDP + TCP | SWIM gossip (peer discovery) |
| `JARVISCORE_BIND_PORT + ZMQ_PORT_OFFSET` (default 8946) | TCP | ZeroMQ agent messaging |

---

## Cloud Deployments

JarvisCore has no cloud-specific dependencies. The pattern is the same on every platform: deploy agents as containers, replace local dev infrastructure with managed equivalents, inject secrets from the platform's secret manager.

### AWS

| JarvisCore dependency | AWS managed equivalent |
|---|---|
| Redis | ElastiCache for Redis (enable persistence) |
| Blob storage | S3 (use `STORAGE_BACKEND=azure` is Azure-specific; for S3, mount a FUSE adapter or use local mode with EFS) |
| Nexus Gateway | ECS (Fargate) or EKS |
| Agents | ECS (Fargate) or EKS |
| Secrets | AWS Secrets Manager or Parameter Store → inject as env vars |
| Athena | EC2 or EKS with persistent volumes |

Inject secrets at container startup:

```bash
# Pull a secret from Secrets Manager and export as env var
export AZURE_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id prod/jarviscore/azure-api-key \
  --query SecretString --output text)
```

For P2P fleets on ECS/EKS, each task/pod needs a unique `JARVISCORE_BIND_PORT` and must be able to reach other nodes on both the SWIM and ZMQ ports. Use a service mesh (App Mesh or Istio) or direct VPC networking — do not route P2P traffic through a load balancer.

### Azure

| JarvisCore dependency | Azure managed equivalent |
|---|---|
| Redis | Azure Cache for Redis (enable RDB + AOF persistence) |
| Blob storage | Azure Blob Storage — `STORAGE_BACKEND=azure`, `AZURE_STORAGE_CONNECTION_STRING` |
| Nexus Gateway | Azure Container Apps or AKS |
| Agents | Azure Container Apps or AKS |
| Secrets | Azure Key Vault → inject via Key Vault references or Managed Identity |
| Athena | AKS with persistent volumes (Azure Disk or Azure Files) |

Azure Blob Storage is the native backend — no adapter needed:

```bash
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_STORAGE_CONTAINER=jarviscore
```

Use Managed Identity rather than connection strings where possible. Assign the `Storage Blob Data Contributor` role to the agent's Managed Identity.

### GCP

| JarvisCore dependency | GCP managed equivalent |
|---|---|
| Redis | Memorystore for Redis (enable persistence) |
| Blob storage | Cloud Storage (use local mode + FUSE or a custom storage backend) |
| Nexus Gateway | Cloud Run or GKE |
| Agents | Cloud Run or GKE |
| Secrets | Secret Manager → inject via Cloud Run secret references or Workload Identity |
| Athena | GKE with persistent volumes (Persistent Disk) |

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

The Kernel enforces hard limits on agent reasoning loops. Review these defaults and tune for your workload:

```bash
# Maximum OODA loop iterations per task (default: 30)
KERNEL_MAX_TURNS=30

# Maximum total tokens across a task (default: 80,000)
KERNEL_MAX_TOTAL_TOKENS=80000

# Wall-clock time limit per task in milliseconds (default: 180,000 = 3 minutes)
KERNEL_WALL_CLOCK_MS=180000

# Token budget splits within a turn
KERNEL_THINKING_BUDGET=56000
KERNEL_ACTION_BUDGET=24000
```

For long-running research tasks, increase `KERNEL_MAX_TURNS` and `KERNEL_WALL_CLOCK_MS`. For cost-sensitive deployments, tighten them. A task that exceeds these limits returns a timeout result — it does not crash the agent process.

---

## Security Checklist

- **Never bake secrets into Docker images.** Inject all credentials at runtime.
- **Set `NEXUS_SECRET`** — the machine UUID fallback logs a warning and is unreliable in containers.
- **Use `SANDBOX_MODE=remote`** if agents process untrusted input or if generated code must be isolated from the agent process.
- **Set `LOG_LEVEL=INFO`** — `DEBUG` logs include LLM payloads which may contain sensitive context.
- **Restrict `EXECUTION_TIMEOUT`** — the default of 300 seconds is generous. Tune to your expected task durations.
- **Open only the required P2P ports** between fleet members. The SWIM and ZMQ ports must be reachable within the fleet but not exposed to the public internet.
- **Use `HITL_ENABLED=true`** for high-risk agents — the HITL queue requires human approval before executing flagged actions.
