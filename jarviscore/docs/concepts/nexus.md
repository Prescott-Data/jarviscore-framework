---
icon: material/shield-key
---

# Nexus: Credential Federation

Nexus is JarvisCore's answer to two compounding problems in agentic systems: agents need credentials to call external services, but agents should never *handle* credentials — and with 46 integrations, writing authentication glue code for each one is unsustainable.

---

## The N+1 Auth Problem

Without Nexus, every integration requires its own authentication implementation. For N integrations you write N OAuth flows, N API key injection patterns, N token refresh handlers, and N error paths for expired credentials. That is the N+1 problem — and it compounds when you add agents.

Consider what a developer would normally need to write to give an agent access to GitHub, Slack, and Jira:

```python
# GitHub — OAuth2 Bearer
headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}

# Slack — OAuth2 Bearer (different token format)
headers = {"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}

# Jira — Basic Auth (completely different mechanism)
import base64
cred = base64.b64encode(f"{email}:{api_token}".encode()).decode()
headers = {"Authorization": f"Basic {cred}"}
```

Three providers, three auth patterns, three environment variables to manage, and three separate token expiry and refresh paths. Now scale that to 46 integrations across a multi-agent fleet.

**Nexus collapses this to one interface:**

```python
# Every provider — same call, regardless of auth type
response = await nexus_call("GET", "https://api.github.com/user")
response = await nexus_call("POST", "https://slack.com/api/chat.postMessage", json={...})
response = await nexus_call("GET", "https://your-org.atlassian.net/rest/api/3/issue/JC-1")
```

The agent and the LLM-generated code never know whether a provider uses OAuth2, API keys, or Basic Auth. Nexus resolves the right strategy and applies it transparently.

---

## How It Works

Nexus operates as a **credential layer that agents talk through**, not a credential store that agents read from. The boundary is enforced by `NexusCallProxy` — the only component that ever touches a raw credential.

```
Agent task → Kernel → CoderSubAgent
                          ↓
                   nexus_call("POST", url, json={...})
                          ↓
                   NexusCallProxy.call(connection_id, method, url)
                          ↓
                   auth_manager.resolve_strategy(connection_id)
                          ↓
                   Nexus Gateway / Local store → credential
                          ↓
                   HTTP request with auth header injected
                          ↓
                   {ok, status_code, json} returned to agent
```

The agent code that triggers this flow never sees the token. The LLM reasoning process never sees the token. The credential exists only in the encrypted store and in memory for the duration of the HTTP call.

### Automatic token refresh

When a provider returns `401`, `NexusCallProxy` does not surface the error to the agent. It:

1. Invalidates its strategy cache for that `connection_id`
2. Calls `refresh_connection` on the Nexus Gateway
3. Retries the original request with the refreshed token

Only if the second request also fails with `401` is the error returned. Agents never implement retry logic for expired tokens.

---

## The Core Security Principle

Agents are not secure boundaries. An LLM-driven agent is a text-processing system — its context window is, by design, readable and injectable. Passing credentials into that context creates a surface for prompt injection attacks: an adversarial input that causes the agent to exfiltrate or misuse the token.

Nexus removes credentials from the agent reasoning surface entirely. The `CoderSubAgent` sandbox receives only an opaque `connection_id` handle. It calls `nexus_call(method, url)` — a closure that has the `connection_id` bound internally. The generated code cannot read the credential even if instructed to.

---

## Multi-Agent Credential Management

In a single-agent system, one developer holds one set of credentials. In a fleet of five agents across ten services, you have 50 credential relationships to manage — each potentially rotating, each potentially needing different scopes.

Nexus centralises this:

- **Register once** — `jarviscore nexus register github` stores the credential once
- **Available everywhere** — any agent on the same Nexus installation can use it
- **Rotate once** — credential rotation happens at the Nexus layer; all agents automatically receive the refreshed token on their next call with no restart or redeployment

---

## The Two Deployment Modes

### Local (development default)

Credentials are stored in `~/.jarviscore/nexus.enc` — an AES-256-GCM encrypted file keyed to the local machine. No Docker required.

```
jarviscore nexus register github → ~/.jarviscore/nexus.enc
Agent calls GitHub → NexusLocalStore decrypts at call time
```

### Gateway (production)

For multi-node deployments, Nexus operates in gateway mode. A central gateway serves credentials to agents across the network. Set it up once:

```bash
jarviscore nexus init   # generates keys, writes .env, starts Docker stack
jarviscore nexus up     # subsequent starts
```

```
Agent node A  ──→ Nexus Gateway ──→ GitHub OAuth token
Agent node B  ──→ Nexus Gateway ──→ Same token, single source of truth
```

The two modes are not mutually exclusive. When `NEXUS_GATEWAY_URL` is set and reachable, the gateway is used. Otherwise the local store is the fallback. You can start locally and migrate to a gateway later without changing any agent code.

> [!IMPORTANT]
> Each team runs their own Nexus Gateway. Do not point agents at a third-party hosted gateway — the gateway holds your credentials.

---

## What Nexus Does Not Do

- **It is not a secrets manager** in the HashiCorp Vault sense. It does not manage arbitrary secrets, rotation policies, or access control lists beyond the agent boundary.
- **It is not an identity provider.** Nexus does not issue tokens — it stores and refreshes tokens issued by third-party providers (GitHub, Slack, Stripe, etc.).
- **It does not replace your application's auth.** If you are building an API on top of JarvisCore, user authentication for your end users is outside Nexus's scope.

Nexus has one job: ensure that agent code can call 46 third-party APIs through a single authenticated interface, without handling credentials directly.

---

## Further Reading

- [Nexus Setup Guide](../guides/nexus.md) — Registering credentials, CLI reference, Gateway API contract, and production deployment
- [System Bundles & Integrations](../guides/integrations.md) — The 46 provider bundles that use Nexus for auth
- [Nexus Framework on GitHub](https://github.com/Prescott-Data/nexus-framework) — The open-source Nexus credential federation framework
