---
icon: material/shield-key
---

# Nexus: Credential Federation

Nexus is JarvisCore's answer to a fundamental problem in agentic systems: agents need credentials to call external services, but agents should never *handle* credentials.

In a naive implementation, you pass tokens directly to agents — in environment variables, in task payloads, or hardcoded. This works for a single agent on a single machine. It breaks down the moment you have a fleet: agents running across processes, machines, and time windows, each needing access to rotating OAuth tokens, short-lived API keys, and service-specific auth flows.

Nexus solves this by acting as a **credential layer that agents talk to, rather than a credential store that agents read from**.

---

## The Core Principle

Agents never receive raw credentials. They receive a sanitised `auth_info` dict at call time — enough for an atom function to make an authenticated API call, nothing more.

```
Agent  →  requests action (e.g. "post to Slack")
             ↓
       Nexus intercepts the call
             ↓
       Decrypts stored credential at call time
             ↓
       Passes auth_info to atom function
             ↓
       Atom calls Slack API
             ↓
       Result returned to agent
```

The agent code that triggers this flow never sees the token. The LLM reasoning process never sees the token. The token exists only in the encrypted local store and in memory for the duration of the API call.

---

## Why Externalise Credentials?

### Agents are not secure boundaries

An LLM-driven agent is a text-processing system. Its context window is, by design, readable and injectable. Passing credentials into that context creates a surface for prompt injection attacks — an adversarial input that causes the agent to exfiltrate or misuse the token.

Nexus removes credentials from the agent's reasoning surface entirely.

### Multi-agent systems multiply the problem

In a single-agent system, one developer holds one set of credentials. In a fleet of five agents across three services, you have 15 credential relationships to manage — each potentially rotating, each potentially needing different scopes.

Nexus centralises this: register once, available to any agent on the same Nexus installation.

### OAuth tokens expire

API keys are static. OAuth2 tokens are not — they expire and must be refreshed. If you pass an OAuth token directly to an agent, it will eventually fail with a 401 and your agent will have no path to recovery.

Nexus manages the token lifecycle: the `AuthenticationManager` handles refresh automatically when a token is within its expiry window, before it's passed to the atom.

---

## The Two Nexus Modes

### Local (default)

Credentials are stored in `~/.jarviscore/nexus.enc` — an AES-256-GCM encrypted file keyed to the local machine. This is the default mode for development and single-node deployments.

```
Developer machine → jarviscore nexus register github → ~/.jarviscore/nexus.enc
Agent process     → atom calls github → NexusLocalStore decrypts at call time
```

### Gateway (production)

For multi-node, multi-machine deployments, Nexus operates in gateway mode. A central `NEXUS_GATEWAY_URL` serves credentials to agents across the network. Agents authenticate to the gateway rather than reading a local file.

```
Agent node A  ──→ Nexus Gateway ──→ GitHub OAuth token
Agent node B  ──→ Nexus Gateway ──→ Same token, single source of truth
```

This is important for production fleets: credential rotation happens once at the gateway, and all agents automatically receive the refreshed token on their next call — no restart, no redeployment.

---

## Relationship to System Bundles

Nexus and System Bundles work together. A system bundle (e.g. `SlackCapabilities`) contains atom functions that make API calls. Those atom functions accept an `auth` parameter — populated at runtime by Nexus.

```python
# The atom doesn't store credentials. It receives them at call time.
async def slack_send_message(channel: str, text: str, auth: dict) -> dict:
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    ...
```

The atom is stateless with respect to auth. Nexus is the stateful counterpart that holds and manages the token.

---

## What Nexus Does Not Do

- **It is not a secrets manager** in the HashiCorp Vault sense. It does not manage arbitrary secrets, rotation policies, or access control lists beyond the agent boundary.
- **It is not an identity provider.** Nexus does not issue tokens — it stores and refreshes tokens issued by third-party providers (GitHub, Slack, Stripe, etc.).
- **It does not replace your own application's auth.** If you are building an API on top of JarvisCore, user authentication for your end users is outside Nexus's scope.

Nexus has one job: ensure that agent code can call third-party APIs securely, without handling credentials directly.

---

## Further Reading

- [Nexus Setup Guide](../guides/nexus.md) — Registering credentials, configuring providers, production deployment
- [System Bundles](system-bundles.md) — How atom functions consume the `auth_info` Nexus provides
- [Nexus Framework on GitHub](https://github.com/Prescott-Data/nexus-framework) — Open-source Nexus credential federation framework
