---
icon: material/console
title: "JarvisCore Command-Line Interface Reference"
description: "Use the jarviscore CLI for project setup, environment checks, smoke tests, Nexus, memory, atom validation, and workflow inspection."
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
  atom        Validate, test, and list integration atoms
  inspect     Read recorded traces from past runs
  verify      Check the journal of decisions and effects
  policy      Check a control policy file; review what strict mode would refuse; who may do what
  replay      Re-simulate recorded agent runs from the journal, every effect stubbed
  evidence    What agents did for a person or tenant; export it for their auditor
  human       Join the mesh as a person
  room        Work together on a shared workspace
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

First-time setup. Generates the stack's secrets, gives your project what agents need, and starts the local Docker stack.

```bash
jarviscore nexus init
```

This command:

1. Generates `NEXUS_ENCRYPTION_KEY`, `NEXUS_STATE_KEY`, `NEXUS_BROKER_API_KEY` and `NEXUS_GATEWAY_API_KEY` into `~/.jarviscore/nexus/stack.env`, a file only your user can read. Keys an earlier `nexus init` wrote to `.env` are moved there, not regenerated, so existing credentials stay readable.
2. Adds `NEXUS_GATEWAY_URL`, `NEXUS_RETURN_URL` and `NEXUS_GATEWAY_API_KEY` to the project `.env`. Agents use only these.
3. Pulls and starts the Nexus Docker stack. The broker and gateway require an API key and listen on `127.0.0.1` only.
4. Waits up to 60 seconds each for the broker and the gateway to become healthy.

Run this command once per machine. Subsequent starts use `jarviscore nexus up`, which also moves any master key it finds in the project `.env`.

!!! warning "Keep the master key out of your project"
    `NEXUS_ENCRYPTION_KEY` decrypts every stored credential. A project `.env` is loaded by every agent process, so the key does not belong there. Back up `~/.jarviscore/nexus/stack.env`: losing it makes stored credentials unreadable.

!!! note "Docker is required"
    `nexus init` requires Docker Desktop or Docker Engine to be installed and running. See [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop).

### nexus up

Starts the local Nexus stack with the secrets in `~/.jarviscore/nexus/stack.env`. Use this for day-to-day restarts after the initial `nexus init`.

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
jarviscore nexus register github --client-id=YOUR_GITHUB_CLIENT_ID
# prompts for the client secret
```

**API-key providers** (Stripe, Airtable, Brevo, Serper):

```bash
jarviscore nexus register stripe
# prompts for the API key
```

A secret left out of the flags is prompted for without echo, so it stays out of your shell history. The flags still work for scripts.

**Any other provider.** The catalog holds defaults for providers already looked up, but it is not a list of what you are allowed to register. Pass the auth type, and for an API key say where the key goes:

```bash
jarviscore nexus register okta --api-key=YOUR_KEY --auth-type=api_key \
    --header-name=Authorization --value-prefix='SSWS '

jarviscore nexus register gitlab --api-key=YOUR_TOKEN --auth-type=api_key \
    --header-name=PRIVATE-TOKEN
```

| Option | Description |
|---|---|
| `--client-id` | OAuth client ID, or username for basic authentication |
| `--client-secret` | OAuth client secret, or password for basic authentication |
| `--api-key` | API key for providers that use key-based authentication |
| `--auth-type` | `oauth2`, `api_key` or `basic_auth`. Required for providers not already in the catalog |
| `--header-name` | Header that carries the credential, such as `X-API-KEY` or `PRIVATE-TOKEN` |
| `--value-prefix` | Scheme word placed before the credential, such as `'Bearer '` or `'SSWS '` |
| `--param-name` | Query parameter that carries the credential, for keys sent in the URL |
| `--credential-field` | Credential field to send when it is not the default for the auth type |

### Where a credential goes

An API key has no standard location. Okta expects `Authorization: SSWS <key>`, Zoho expects `Authorization: Zoho-oauthtoken <token>`, GitLab expects `PRIVATE-TOKEN`, Serper expects `X-API-KEY`, and some providers expect a query parameter. JarvisCore records the location per provider rather than guessing, because a header the provider ignores returns an opaque 401 that is difficult to trace back to its cause.

If you register an API key without saying where it goes, the command stops and tells you which flag to add. OAuth2 defaults to `Authorization: Bearer <token>` as described in RFC 6750, so it needs no placement unless the provider uses its own scheme word.

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

Pulls the published Athena image and starts the Docker stack. Run this once per environment.

```bash
jarviscore memory init
```

Contributors working on Athena itself can build from a local clone:

```bash
git clone https://github.com/Prescott-Data/athena ~/athena
jarviscore memory init --from-source
```

With `--from-source`, a non-standard clone location is set with `ATHENA_DIR`:

```bash
ATHENA_DIR=/path/to/athena jarviscore memory init --from-source
```

The `init` command:

1. Detects an LLM API key from the environment (Gemini, then Azure OpenAI, then OpenAI).
2. Uses `ATHENA_API_KEY` from the environment or `.env`, or creates one. Athena requires it; JarvisCore uses it as a service key.
3. Starts all Athena services with `docker compose up -d`, including a one-time step that creates Athena's long-term memory graph.
4. Waits up to 90 seconds for the health endpoint at `http://localhost:8080/api/v1/health` to report healthy.
5. Writes `ATHENA_URL=http://localhost:8080` and, if it created one, `ATHENA_API_KEY` to the project `.env` file.

!!! note "First-start duration"
    The first run takes about two minutes to pull images. Subsequent starts complete in under 10 seconds.

### memory up

Alias for `memory init`. Starting the stack is idempotent: services already running are left untouched.

```bash
jarviscore memory up
```

### memory status

Reports the health of all memory tiers: Athena, Redis, and blob storage.

```bash
jarviscore memory status
```

Example output:

```
════════════════════════════════════════════════════════════════════════
  JarvisCore Memory Status
════════════════════════════════════════════════════════════════════════
  Athena MemOS  http://localhost:8080  [ok]
    Redis: ok
    MongoDB: ok
    Milvus: ok
    ArangoDB: ok
  Redis  localhost:6379  [connected]
  Blob  Local filesystem  [.jarviscore/blob_storage]
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

---

## jarviscore atom

Developer tooling for validating, testing, and inspecting integration atoms. Use this whenever you add a custom atom to a bundle before marking it as `verified` in `seed_registry.py`.

### atom test

Runs structural or live-connection checks against one or more atoms.

```bash
jarviscore atom test --bundle <bundle> --mode <dry-run|integration> [options]
```

| Option | Description |
|---|---|
| `--bundle` | Bundle name to test (e.g. `slack`, `github`, `stripe`) |
| `--atom` | Test a single atom instead of the whole bundle |
| `--mode` | `dry-run` (default) or `integration` |
| `--connection-id` | Nexus connection handle: required for `integration` mode |
| `--nexus-url` | Gateway URL (defaults to `NEXUS_GATEWAY_URL` or `http://localhost:8090`) |
| `--all` | Test every atom across all bundles: `dry-run` only |

**Dry-run mode**: structural checks only, no network required:

```bash
# Check all atoms in the slack bundle
jarviscore atom test --bundle slack --mode dry-run

# Check a single atom
jarviscore atom test --bundle slack --atom slack_send_message --mode dry-run

# Check every atom across the installed bundles
jarviscore atom test --mode dry-run --all
```

Dry-run validates:

| Check | What it validates |
|---|---|
| File exists | `integrations/atoms/<bundle>/<atom>.py` is present |
| Valid Python | File parses without a `SyntaxError` |
| Function name | Top-level function name matches filename stem |
| Contract | Async function, authenticates only through `nexus_call` |
| Return type | Return annotation is `-> dict` |
| Docstring | Function has a docstring |
| Return statement | At least one `return` with a value |
| Forbidden usage | No `subprocess`, `pickle`, `ctypes`, `eval`, `exec` |

**Integration mode**: passes dry-run, then verifies a Nexus `connection_id` resolves:

```bash
jarviscore atom test \
    --bundle github \
    --connection-id abc123 \
    --mode integration
```

The integration check does not call the provider API: it confirms the Nexus Gateway is reachable and the `connection_id` resolves to a token payload. API behaviour must be verified manually.

!!! note "Gateway required for integration mode"
    `--mode integration` requires `NEXUS_GATEWAY_URL` to be set and the Nexus stack to be running. Use `jarviscore nexus status` to confirm the gateway is healthy first.

### atom list

Lists the built-in bundle directories and atom files shipped with your installed
version. Use this local inventory as the source of truth for catalog availability;
it does not query a running registry or certify that atoms have been verified
against live provider APIs.

```bash
# All bundles
jarviscore atom list

# Single bundle
jarviscore atom list --bundle slack
```

Illustrative output (names are abbreviated; counts come from your installation):

```
JarvisCore Atom Registry
jarviscore/integrations/atoms

  slack  (<atom count> atoms)
    · slack_send_message
    · ...

... remaining installed bundles ...

<bundle count> bundles  ·  <total atom count> atoms total
```

The complete output reports totals from the installed catalog, counting atom
files rather than parsing their functions and excluding package initializers.
These totals change as bundles and atoms are added or removed. Use `atom test`
for structural validation; listing an atom is not a validation result.

See [Testing Atoms](../guides/testing-atoms.md) for the full workflow: from writing a new atom to promoting it to `verified`.

---

## jarviscore human

Puts a person on the mesh as a peer, and answers the work that waits for people. See [People as Peers](../guides/human-peers.md).

### human join

Starts a mesh node whose only agent is a `HumanAgent` for you. Other nodes see you in their roster and route work for your capabilities to you. Each piece of work appears in your terminal, where you type your answer and choose how to send it.

```bash
jarviscore human join alice --capabilities review,approve --seed 10.0.0.5:7949
```

| Option | Default | Description |
|---|---|---|
| `name` | (required) | Your role on the mesh |
| `--capabilities` | (required) | Comma-separated capabilities; `human` is always added |
| `--seed` | (none) | `host:port` of any node already on the mesh |
| `--host` | `127.0.0.1` | Address to listen on; use a LAN or VPN address to be reachable |
| `--port` | `7960` | SWIM port; messages use this port + 1000 |
| `--redis-url` | (none) | Shared Redis, to claim workflow steps from the ledger |
| `--no-terminal` | off | Leave work in the HITL inbox instead of showing it here |
| `--describe` | (none) | How planners and peers should think of you |

### human inbox

Lists work waiting for people in the HITL inbox: everyone's, or one person's.

```bash
jarviscore human inbox [PERSON] [--dir hitl_inbox]
```

### human answer

Answers a piece of work. The answer is the step's result; a rejection or a refusal fails the step with your reason.

```bash
jarviscore human answer ITEM_ID "Swap the second sentence"
jarviscore human answer ITEM_ID --approve "ship it"
jarviscore human answer ITEM_ID --reject "The numbers are wrong"
jarviscore human answer ITEM_ID --decline "Not my area"
```

| Option | Default | Description |
|---|---|---|
| `--approve [NOTE]` | | Sign it off |
| `--reject [WHY]` | | Refuse it; the step fails with your reason |
| `--decline [WHY]` | | You will not or cannot do it |
| `--by` | the person it is for | Who is answering |
| `--dir` | `hitl_inbox` | HITL inbox directory |

---

## jarviscore room

Rooms from a terminal, for developers and operators. See [Rooms](../guides/rooms.md). Rooms live in the mesh's Redis (`REDIS_URL` or `--redis-url`), in a tenant (`JARVISCORE_TENANT` or `--tenant`, default `default`).

| Command | What it does |
|---|---|
| `room create ROOM --as NAME [--from DIR]` | Open a private room owned by NAME, optionally with a directory's files |
| `room status ROOM --as NAME` | Current version and open proposals NAME can see |
| `room watch ROOM --as NAME [--once] [--new]` | Follow the room: requests, plans, steps, proposals and decisions. `--new` starts from now |
| `room ask ROOM "GOAL" --as NAME [--timeout S]` | Ask the mesh's agents to do it on the room's files, as NAME |
| `room diff ROOM PROPOSAL --as NAME` | What a proposal changes |
| `room accept ROOM PROPOSAL --as NAME` | Merge it; exits 1 on a conflict |
| `room reject ROOM PROPOSAL "WHY" --as NAME [--redo]` | Turn it down; `--redo` asks the agents again with your reason |
| `room release ROOM PROPOSAL --as NAME` | Release work held for NAME to the room |
| `room members ROOM` | Who can see the room, their roles, and its shared systems |
| `room role ROOM PERSON viewer\|editor\|owner\|none --as NAME` | Set or remove a role (owners) |
| `room visibility ROOM members\|tenant --as NAME [--tenant-role viewer\|editor]` | Who can see the room (owners) |
| `room connectors ROOM [PROVIDER ...] --as NAME` | Systems whose data everyone in the room may see (owners) |
| `room audit ROOM [--days N] [--json]` | Everything done in the room: who, what, why, with whose access, at what cost |
| `room caps [PERSON] [--tokens-per-day N] [--tokens-per-month N] [--usd-per-day X] [--usd-per-month X] [--clear ...]` | Spending caps for the tenant, or one person in it, and their usage |
| `room checkout ROOM DIR --as NAME` | Copy the current files into an empty directory |
| `room push DIR [-m TITLE] --as NAME [--accept]` | Propose what changed in a checkout |
| `room slack ROOM --channel ID [--seed HOST:PORT] [--people NAME] [--capabilities LIST] [--timeout S]` | Serve the room in a Slack channel, with Slack connected through Nexus; see [Chat Surfaces](../guides/chat-surfaces.md#slack) |

```bash
export JARVISCORE_TENANT=acme
jarviscore room ask launch "Fill in the Risks section of plan.md from brief.md" --as alice
jarviscore room diff launch p-789486bf --as bob
jarviscore room reject launch p-789486bf "One line per risk, please" --as bob --redo
```

These commands act with the access of whoever holds the Redis URL. `--as` names the person an action is recorded for and whose room role is checked; it is not a login. People use rooms through your product or a chat surface, which take the person from their own authentication.

---

## jarviscore inspect

Reads recorded traces and shows what your agents actually did. Requires `TRACE_ENABLED=true` on the runs you want to inspect.

```bash
# List recorded runs
jarviscore inspect

# Timeline for one run (workflow id prefix is enough)
jarviscore inspect wf-2024

# Failures and recoveries only
jarviscore inspect wf-2024 --errors

# Events for a single step
jarviscore inspect wf-2024 --step analyze
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `workflow` | `str` | (none) | Workflow id, prefix match accepted; omit to list runs |
| `--dir` | `str` | `./.jarviscore/traces` | Directory containing trace JSONL files |
| `--step` | `str` | (none) | Only show events for this step id |
| `--errors` | flag | off | Only show failures and recoveries |

See [Observability](../guides/observability.md) for how traces are recorded and what each event means.

---

## jarviscore verify

Checks the journal of decisions and effects (provider calls and every other
mediated effect), offline. It needs no keys and
no network, so it runs the same on a copy handed to an auditor.

```bash
# This deployment's journal (JOURNAL_DIR)
jarviscore verify

# A copy somewhere else
jarviscore verify /path/to/journal

# The report as JSON
jarviscore verify --json

# An export of one person's or tenant's runs (jarviscore evidence --export)
jarviscore verify --export /path/to/export
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `journal_dir` | `str` | `JOURNAL_DIR` (`./.jarviscore/journal`) | Journal to check |
| `--json` | flag | off | Print the report as JSON (with `problems` and `notes`) |
| `--export` | flag | off | Check an export: runs it left out are expected missing. A plain `verify` refuses an export |

Notes (not problems) report a run still being written or events after a run's
registered head.

It checks each run's hash chain, that each run ends where the head log
registered it, that every effect followed an allow decision, and that every
grounded call cites reads that are in the record. Exit
status: `0` intact, `1` problems found, `2` no journal. See
[Control and Evidence](../concepts/control-and-evidence.md) for what it detects and what it does not yet.

---

## jarviscore replay

Re-simulates recorded agent runs from the journal. Every model call, gate and
tool is answered from the record, so nothing is called and nothing acts.

```bash
jarviscore replay                        # every recorded run in JOURNAL_DIR
jarviscore replay /path/to/journal wf-12/pay
jarviscore replay --json
```

A run reproduces when the agent makes the same decisions and ends the same way;
otherwise the report names the first decision where it diverged. Exit status:
`0` all reproduced, `1` any diverged, `2` nothing to replay. Needs
`JOURNAL_CAPTURE=full` (the default). See [Replay](../concepts/control-and-evidence.md#replay).

---

## jarviscore evidence

What agents did for one person, or for everyone in a tenant (a key ending in
`/`), from the journal; export it for an auditor; erase a person's replay content.

```bash
jarviscore evidence acme/u_123                       # each run, decision and approval for them
jarviscore evidence acme/ /path/to/journal --json    # a whole tenant, as JSON
jarviscore evidence acme/ --export acme-evidence/    # copy those runs, verifiable on their own
jarviscore evidence acme/ --export out/ --content    # ... with replay content (personal data)
jarviscore evidence acme/u_123 --erase               # what erasing their replay content removes
jarviscore evidence acme/u_123 --erase --yes         # erase it
```

| Option | Description |
|---|---|
| `who` | A person key (`acme/u_123`) or a tenant (`acme/`) |
| `journal_dir` | Default `JOURNAL_DIR` |
| `--export DIR` | Copy their runs and the head log into an empty `DIR`, with `export.json`; runs shared with others are left out and listed |
| `--content` | With `--export`: also copy the content replay needs |
| `--erase [--yes]` | Count, then erase, the replay content only their runs used; the journal still verifies |
| `--json` | JSON output |

Exit status: `0`; `1` when no person or tenant is given; `2` when there is no
journal, nothing was done for them, or the `--export` directory is not empty.
See [Agents That Act for Your Users](../guides/acting-for-your-users.md#7-evidence-per-user-and-per-tenant).

---

## jarviscore policy

Checks a control policy file, and reviews a journal for what strict mode refuses.
All three run offline.

```bash
# Every rule reads as written? (default: CONTROL_POLICY_PATH)
jarviscore policy check control-policy.yaml

# What strict mode would refuse (report mode) or refused (strict), grouped,
# with what to do about each (default: JOURNAL_DIR)
jarviscore policy review

# Who may do what: each operation's scope and limits, and the grants on file
jarviscore policy scopes control-policy.yaml

# Any of them as JSON
jarviscore policy check control-policy.yaml --json
```

`check` names every rule a deployment would silently fail closed on (an unknown
section, a match key a rule can never meet, a grounding requirement that refers
to nothing bound, an unreadable `effects` rule), and says whether this host can
confine the sandbox, which strict mode needs. Exit status: `0` every rule reads
as written, `1` problems found, `2` no policy file. `review` exits `0`. `scopes`
lists each scope requirement (what it matches, who must hold which scope, its
limits), the grants on file and what unattended work holds, and notes a
requirement matched only by integration name; it exits `1` when the file or any
requirement cannot be read, and `2` when there is no policy file. See [Turning On Control](../guides/control-policy.md) and
[your organisation's scopes](../guides/acting-for-your-users.md#4-hold-them-to-your-organisations-scopes).

---

