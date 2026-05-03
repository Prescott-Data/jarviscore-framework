---
icon: material/console
---

# CLI Reference

The `jarviscore` command-line interface provides tools for project setup, infrastructure management, and operational inspection of running agents. All commands are available after installing the framework package.

---

## Command Groups

```
jarviscore <command> [subcommand] [options]

Commands:
  init        Scaffold a new project
  check       Validate installation and configuration
  smoketest   Run a quick inference test
  nexus       Manage credential infrastructure
  memory      Manage agent memory infrastructure
```

---

## jarviscore init

Scaffolds a new project by creating an `.env.example` file in the current directory.

```bash
jarviscore init
```

Use the `--examples` flag to also copy example agent scripts into the project:

```bash
jarviscore init --examples
```

After running `init`, copy the example file and populate it with your configuration:

```bash
cp .env.example .env
```

---

## jarviscore check

Validates your installation, environment configuration, and optionally tests live LLM connectivity.

```bash
jarviscore check
```

| Flag | Description |
|---|---|
| `--validate-llm` | Makes live inference calls to verify each configured LLM provider is reachable |
| `--verbose` | Shows detailed information for all checks, not just failures |

The check command inspects the following in order:

1. Python version (3.10 or later required)
2. `jarviscore` package installation and version
3. Core dependencies (`pydantic`, `pydantic_settings`)
4. `.env` file presence
5. LLM provider configuration
6. Sandbox configuration

Exit code `0` indicates all required checks passed. Exit code `1` indicates at least one issue was found.

---

## jarviscore smoketest

Runs a minimal end-to-end inference test to confirm the framework can instantiate an agent and complete a task.

```bash
jarviscore smoketest
```

This command requires at least one LLM provider to be configured. It does not require Redis, Athena, or any other infrastructure.

---

## jarviscore nexus

Manages the Nexus credential gateway, which agents use to call third-party OAuth and API-key protected services.

### nexus init

First-time setup. Generates encryption keys, writes them to `.env`, and starts the local Docker stack.

```bash
jarviscore nexus init
```

This command:

1. Generates `NEXUS_ENCRYPTION_KEY` and `NEXUS_STATE_KEY` if they are not already present in `.env`.
2. Adds `NEXUS_GATEWAY_URL=http://localhost:8090` and `NEXUS_RETURN_URL=http://localhost:8000/oauth/callback` to `.env`.
3. Pulls and starts the Nexus Docker stack with `docker compose up -d`.
4. Waits up to 30 seconds for the broker to become healthy.

Run this command once per project. Subsequent starts use `jarviscore nexus up`.

!!! note "Docker is required"
    `nexus init` requires Docker Desktop or Docker Engine to be installed and running. See [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop).

### nexus up

Starts the local Nexus stack without regenerating keys. Use this for day-to-day restarts after the initial `nexus init`.

```bash
jarviscore nexus up
```

### nexus register

Registers a third-party provider's credentials with the local credential store or the live gateway.

```bash
jarviscore nexus register <provider> [options]
```

**OAuth2 providers** (GitHub, Slack, Notion, HubSpot, Linear, Google Sheets, Google Drive):

```bash
jarviscore nexus register github \
    --client-id=YOUR_GITHUB_CLIENT_ID \
    --client-secret=YOUR_GITHUB_CLIENT_SECRET
```

**API-key providers** (Stripe, Airtable, Brevo, Mailchimp, Apollo):

```bash
jarviscore nexus register stripe --api-key=sk_live_...
```

| Option | Description |
|---|---|
| `--client-id` | OAuth client ID, or username for basic authentication |
| `--client-secret` | OAuth client secret, or password for basic authentication |
| `--api-key` | API key for providers that use key-based authentication |

Credentials are stored AES-256-GCM encrypted at rest in the local credential store. If `NEXUS_GATEWAY_URL` is set and the gateway is reachable, credentials are also registered with the gateway.

Developer console URLs for each supported provider:

| Provider | Console URL |
|---|---|
| GitHub | https://github.com/settings/developers |
| Slack | https://api.slack.com/apps |
| Notion | https://www.notion.so/my-integrations |
| HubSpot | https://developers.hubspot.com/ |
| Google Sheets / Drive | https://console.cloud.google.com/apis/credentials |
| Linear | https://linear.app/settings/api |
| Stripe | https://dashboard.stripe.com/apikeys |
| Airtable | https://airtable.com/create/tokens |
| Brevo | https://app.brevo.com/settings/keys/api |
| Apollo | https://app.apollo.io/#/settings/integrations/api |

### nexus list

Lists all registered providers from the local credential store and, if configured, from the live gateway.

```bash
jarviscore nexus list
```

### nexus test

Tests an OAuth flow end-to-end by requesting a connection through the gateway and opening the provider's authorisation URL.

```bash
jarviscore nexus test github
```

| Option | Description |
|---|---|
| `--user-id` | User ID for the test connection (defaults to `jarviscore-test`) |

!!! note "Gateway required"
    `nexus test` requires `NEXUS_GATEWAY_URL` to be set and the gateway to be running. Use `jarviscore nexus status` to confirm the gateway is healthy before running a test.

### nexus status

Checks gateway reachability and the state of each Docker container in the local Nexus stack.

```bash
jarviscore nexus status
```

---

## jarviscore memory

Manages the Athena MemOS memory infrastructure.

### memory init

Builds and starts the Athena Docker stack from source. Run this once per environment.

```bash
jarviscore memory init
```

Before running this command, clone the Athena repository:

```bash
git clone https://github.com/Prescott-Data/athena ~/athena
```

If your Athena clone is in a non-standard location, set `ATHENA_DIR`:

```bash
ATHENA_DIR=/path/to/athena jarviscore memory init
```

The `init` command:

1. Locates the Athena source repository.
2. Detects an LLM API key from the environment (Gemini, then Anthropic, then OpenAI).
3. Builds all Athena services with `docker compose up -d --build`.
4. Waits up to 90 seconds for the health endpoint at `http://localhost:8080/api/v1/health` to return `ok`.
5. Writes `ATHENA_URL=http://localhost:8080` to the project `.env` file.

!!! note "First-build duration"
    The initial build takes approximately two minutes because Milvus is compiled from source. Subsequent starts use Docker layer caching and complete in under 10 seconds.

### memory status

Reports the health of all memory tiers: Athena, Redis, and blob storage.

```bash
jarviscore memory status
```

Example output:

```
════════════════════════════════════════════════════════════════════════
  JarvisCore Memory — Status
════════════════════════════════════════════════════════════════════════
  Athena MemOS  http://localhost:8080  [ok]
    Redis: ok
    MongoDB: ok
    Milvus: ok
    ArangoDB: ok
  Redis  localhost:6379  [connected]
  Blob  Local filesystem  [./blob_storage]
```

### memory context

Dumps recent Short-Term Memory (STM) events and Mid-Term Memory (MTM) cognitive chains for a specific agent.

```bash
jarviscore memory context --agent researcher
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--agent` | `str` | Required | The agent name to inspect |
| `--limit` | `int` | `20` | Maximum number of STM events to display |

### memory search

Performs a semantic search across an agent's full memory using the Athena vector index.

```bash
jarviscore memory search --agent researcher --query "market analysis findings"
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--agent` | `str` | Required | The agent name to search |
| `--query` | `str` | Required | Natural language search query |
| `--limit` | `int` | `5` | Maximum number of results to return |

Results include a similarity score, the source memory tier (STM or MTM), and a content preview.
