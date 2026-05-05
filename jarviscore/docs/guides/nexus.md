---
icon: material/key-variant
---

# Nexus: Credential Management

Nexus is JarvisCore's credential management system — and an [open-source framework in its own right](https://github.com/Prescott-Data/nexus-framework). It gives agents a secure way to call third-party services — GitHub, Slack, Stripe, and others — without embedding credentials in source code or exposing them to agent reasoning.

Credentials are encrypted at rest using AES-256-GCM and are never returned to agent code. Agents receive only a sanitised `auth_info` dict at call time.

---

## How It Works

1. You register a provider's credentials once using `jarviscore nexus register`.
2. Credentials are written to `~/.jarviscore/nexus.enc` — an AES-256-GCM encrypted file keyed to your machine.
3. When an agent calls a registered provider, the `NexusLocalStore` retrieves and decrypts the credentials at call time and passes them to the provider's atom function.
4. Agent code never sees the raw credentials.

---

## Registering Credentials

### OAuth2 providers

```bash
jarviscore nexus register github \
    --client-id=YOUR_GITHUB_CLIENT_ID \
    --client-secret=YOUR_GITHUB_CLIENT_SECRET
```

Supported OAuth2 providers: `github`, `slack`, `notion`, `hubspot`, `linear`, `google-sheets`, `google-drive`.

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

- **Encryption:** AES-256-GCM (authenticated encryption — integrity + confidentiality)
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

The `NexusLocalStore` is accessed via `jarviscore.nexus.store.get_store()`. In normal usage you do not call it directly — provider atom functions receive `auth_info` automatically. For custom integrations, you can retrieve credentials as follows:

```python
from jarviscore.nexus.store import get_store

store = get_store()

# Check if a provider is registered
creds = store.get("github")
if not creds:
    item_id = self.hitl.request(
        title="GitHub credentials not registered",
        content="Register GitHub OAuth credentials with: jarviscore nexus register github",
        urgency="high",
        category="auth_required",
    )
    return {"status": "waiting_for_auth", "hitl_id": item_id}

# Get auth_info for calling the provider
auth_info = store.build_auth_info("github")
# auth_info = {"access_token": "...", "client_id": "...", "client_secret": "..."}
```

`build_auth_info` shapes the credential dict based on `auth_type`:

| `auth_type` | `auth_info` keys |
|---|---|
| `oauth2` | `access_token`, `client_id`, `client_secret` |
| `api_key` | `api_key` |
| `basic_auth` | `username`, `password` |

---

## The Nexus Gateway (Optional)

The local encrypted store handles credentials for single-developer and small team use. For multi-user deployments where agents act on behalf of individual users (each with their own OAuth tokens), the **Nexus Gateway** provides full OAuth flow management.

> [!NOTE]
> **The two modes are not mutually exclusive — the CLI chooses automatically.**
> When you run `jarviscore nexus register`, the CLI checks whether `NEXUS_GATEWAY_URL` is set and reachable. If it is, credentials are registered with the gateway. If it is not set, or if the gateway is unreachable, credentials are written to the local store (`~/.jarviscore/nexus.enc`) and a warning is printed. You can start without a gateway and migrate to one later — the local store keeps working regardless.

The gateway is managed entirely via the `jarviscore` CLI — no separate install required. It runs as a Docker-composed stack. Set it up once per environment:

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

When `NEXUS_GATEWAY_URL` is set, the CLI registers providers by calling the Gateway directly. You should not need to call this manually — `jarviscore nexus register` handles it — but the contract is documented here for completeness.

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
> All examples assume `http://localhost:8090` — the default local Docker stack started by `jarviscore nexus init`. Substitute your own Gateway URL in production. **Do not point developers at a third-party hosted gateway** — each team runs their own Nexus stack.

---

## Handling Auth Failures in Agents

When a credential is missing or expired, the correct pattern is to escalate via HITL rather than failing silently:

```python
from jarviscore import CustomAgent
from jarviscore.nexus.store import get_store

class GitHubAgent(CustomAgent):
    role = "github-integration"

    async def on_peer_request(self, msg) -> dict:
        store = get_store()
        context = msg.data.get("context", {})

        if not store.get("github"):
            item_id = self.hitl.request(
                title="GitHub credentials missing",
                content=(
                    "The GitHub integration requires OAuth credentials.\n\n"
                    "Run: `jarviscore nexus register github --client-id=X --client-secret=Y`"
                ),
                urgency="high",
                category="auth_required",
                context={"workflow_id": context.get("workflow_id")},
            )
            resolution = await self.hitl.wait(item_id, timeout=3600)
            if not resolution.is_approved:
                return {"status": "cancelled"}

        auth_info = store.build_auth_info("github")
        # proceed with GitHub API calls using auth_info
        ...
```

---

## NexusLocalStore API

For advanced use cases, the full `NexusLocalStore` API:

```python
from jarviscore.nexus.store import get_store

store = get_store()

# Register or update credentials
store.register("github", {
    "auth_type": "oauth2",
    "client_id": "Iv1.abc123",
    "client_secret": "secret",
})

# Retrieve raw credential dict (includes all stored fields)
creds = store.get("github")

# List registered providers
providers = store.list()   # ["github", "stripe"]

# Delete credentials
store.delete("stripe")

# Safe summary (no secrets) for display
summary = store.get_summary()
# [{"provider": "github", "auth_type": "oauth2", "client_id": "Iv1.****", "registered_at": "..."}]

# Get auth_info dict for passing to provider functions
auth_info = store.build_auth_info("github")
```
