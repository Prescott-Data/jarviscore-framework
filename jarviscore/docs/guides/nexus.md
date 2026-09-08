---
icon: material/key-variant
---

# Nexus: Credential Management

Nexus is JarvisCore's credential management system and an [open-source framework in its own right](https://github.com/Prescott-Data/nexus-framework). It solves the N+1 authentication problem by providing a single `nexus_call` interface for the built-in service integrations. Nexus handles credential resolution, token refresh, and auth strategy selection so that agents never deal with credentials directly. Inspect your installed integration catalog with [`jarviscore atom list`](../reference/cli.md#atom-list).

> [!NOTE]
> This page is the operational reference covering CLI commands, encryption details, and the Gateway API contract. For the conceptual model explaining why Nexus exists, how `NexusCallProxy` works, and the security design, see [Nexus: Credential Federation](../concepts/nexus.md).

---

## How It Works

1. You register a provider application or credential once using `jarviscore nexus register`.
2. Credentials are written to `~/.jarviscore/nexus.enc`: an AES-256-GCM encrypted file keyed to your machine.
3. OAuth application registration and account consent remain separate states.
  A registered app cannot sign calls until an account is connected.
4. Generated code sends method, URL, provider and request data to the trusted
  parent through `nexus_call`. The parent resolves and places the credential
  only after checking that the destination host belongs to that provider.
5. Agent code and the child execution process never receive raw credentials.

---

## Registering Credentials

### OAuth2 providers

```bash
jarviscore nexus register github \
    --client-id=YOUR_GITHUB_CLIENT_ID \
    --client-secret=YOUR_GITHUB_CLIENT_SECRET
```

Built-in OAuth2 profiles include `github`, `slack`, `notion`, `hubspot`,
`linear`, `google-sheets`, `google-drive`, `gmail`, and `google-calendar`.

### API-key providers

```bash
jarviscore nexus register stripe --api-key=sk_live_...
jarviscore nexus register airtable --api-key=patXXXXXXXX
```

Supported API-key providers: `stripe`, `airtable`, `brevo`, `mailchimp`, `apollo`.

### Verify registration

```bash
jarviscore nexus list
```

Output shows a masked credential summary (no secrets):

```
Provider   Auth type   Client ID    Registered
──────────────────────────────────────────────
github     oauth2      ghXX****     2026-05-01
stripe     api_key     sk_l****     2026-05-01
```

---

## Encryption Details

Credentials are stored in `~/.jarviscore/nexus.enc`:

- **Encryption:** AES-256-GCM (authenticated encryption: integrity + confidentiality)
- **Key derivation:** PBKDF2-HMAC-SHA256, 260,000 iterations (OWASP 2024 recommendation)
- **Salt:** Per-machine, generated once and stored at `~/.jarviscore/.salt`. Never changes.
- **Secret input:** `NEXUS_SECRET` env var if set; falls back to machine UUID (MAC address).
- **Nonce:** 12-byte random, unique per write.

Set `NEXUS_SECRET` in your `.env` for stronger key derivation:

```bash title=".env"
NEXUS_SECRET=a-long-random-secret-only-you-know
```

Without `NEXUS_SECRET`, the key is derived from the machine's hardware UUID. Credentials encrypted on one machine cannot be decrypted on another.

---

## Using Nexus in Agent Code

Use provider atoms where one exists. Custom generated code uses the injected
asynchronous `nexus_call`; it never reads the local store or builds an auth
header:

```python
async def main():
  response = await nexus_call(
    "GET",
    "https://api.github.com/repos/Prescott-Data/jarviscore-framework",
    provider="github",
  )
  if not response["ok"]:
    return {"success": False, "error": response["body"]}
  return {"success": True, "repository": response["json"]}
```

One isolated execution may use several connected systems by naming the provider
on each call:

```python
gmail = await nexus_call("GET", gmail_url, provider="gmail")
calendar = await nexus_call("GET", calendar_url, provider="google_calendar")
crm = await nexus_call("GET", hubspot_url, provider="hubspot")
```

The model receives connected provider names as non-secret context. The trusted
parent resolves each name to an opaque connection handle and enforces provider
host ownership. A missing connection yields for consent; it never causes another
provider's credential to be tried.

> [!WARNING]
> `get_store().get()` is framework-internal credential access. Do not place its
> result, `auth_info`, tokens, API keys, or authorization headers in agent code,
> prompts, context, logs, or output.

---

## The Nexus Gateway (Optional)

The local encrypted store handles credentials for single-developer and small team use. For multi-user deployments where agents act on behalf of individual users (each with their own OAuth tokens), the **Nexus Gateway** provides full OAuth flow management.

> [!NOTE]
> **The two modes are not mutually exclusive: the CLI chooses automatically.**
> When you run `jarviscore nexus register`, the CLI checks whether `NEXUS_GATEWAY_URL` is set and reachable. If it is, credentials are registered with the gateway. If it is not set, or if the gateway is unreachable, credentials are written to the local store (`~/.jarviscore/nexus.enc`) and a warning is printed. You can start without a gateway and migrate to one later: the local store keeps working regardless.



The gateway is managed entirely via the `jarviscore` CLI: no separate install required. It runs as a Docker-composed stack. Set it up once per environment:

```bash
jarviscore nexus init
```

This generates encryption keys, adds `NEXUS_GATEWAY_URL` and `NEXUS_RETURN_URL` to `.env`, and starts the Docker stack. After `init`, subsequent starts use:

```bash
jarviscore nexus up
```

Test an OAuth flow end-to-end:

```bash
jarviscore nexus test github --user-id=alice
```

Check gateway health:

```bash
jarviscore nexus status
```

---

## Gateway API Contract

When `NEXUS_GATEWAY_URL` is set, the CLI registers providers by calling the Gateway directly. You should not need to call this manually (`jarviscore nexus register` handles it) but the contract is documented here for completeness.

**Register a provider:** `POST /v1/providers`

The payload must wrap all fields in a `profile` object and use `name` (not `provider`) as the identifier:

=== "OAuth2"

    ```json
    {
      "profile": {
        "name": "github",
        "auth_type": "oauth2",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET",
        "scopes": ["repo", "read:user"],
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token"
      }
    }
    ```

=== "API Key"

    ```json
    {
      "profile": {
        "name": "stripe",
        "auth_type": "api_key",
        "params": {
          "credential_schema": {
            "type": "object",
            "required": ["api_key"],
            "properties": {
              "api_key": { "type": "string", "title": "API Key" }
            }
          }
        }
      }
    }
    ```

**List registered providers:** `GET /v1/providers`

**Check gateway health:** `GET /health`

> [!NOTE]
> All examples assume `http://localhost:8090` (the default local Docker stack started by `jarviscore nexus init`. Substitute your own Gateway URL in production. **Do not point developers at a third-party hosted gateway**) each team runs their own Nexus stack.

---

## Handling Auth Failures in Agents

Do not inspect the credential store or convert a provider response into an auth
decision yourself. Name the provider in task context; JarvisCore distinguishes
registered, connected and attention-required states, then yields the same run for
consent when needed:

```python
result = await agent.execute_task({
  "task": "Summarize the open issues in our GitHub repository.",
  "context": {"system": "github"},
})
```

The Desk or another hosted flow receives a typed consent event. After approval,
the checkpointed workflow and step resume; generated code still receives no
token. HTTP 401/403 is retained as boundary evidence, not treated by itself as a
deterministic auth category.

---

## NexusLocalStore Administration

Application code should use the CLI and `nexus_call`. Trusted administration and
diagnostics may inspect non-secret state:

```python
from jarviscore.nexus.store import get_store

store = get_store()
providers = store.list()   # ["github", "stripe"]
state = store.connection_state("github")  # absent, registered, or connected
summary = store.get_summary()
```

Methods that return stored entries are framework-internal because those entries
may contain credentials. Never expose them to an agent, prompt, trace or API.
