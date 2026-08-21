# JarvisCore Promotional LLM Access

## Engineering and GTM handoff

This document explains the temporary JarvisCore launch promotion, what has
already been implemented in the public Python library, and what must still be
built on the JarvisCore developer site.

The intended readers are engineering, GTM, security, and whoever implements
the registration and inference service.

## Summary

The first **X verified developers** who register for the promotion receive
limited hosted LLM access for use with JarvisCore.

Developers do not receive an OpenAI, Azure, Gemini, or other upstream provider
API key. They receive a unique Prescott promotional token in the form:

```text
jc_trial_...
```

The JarvisCore library sends that token to a fixed Prescott endpoint. The
Prescott service validates the entitlement, enforces the campaign limits, calls
the upstream model using a server-side provider credential, and returns the
complete result.

The promotion is granted to the first X verified registrations, not the first X
PyPI downloads. PyPI downloads cannot reliably identify individual people and
include CI jobs, mirrors, bots, and repeated installations.

## Status

The public-library work is implemented on:

```text
Branch: feat/promotional-llm-client
Commit: 36daf75 feat: add promotional LLM client
```

The developer-site registration and inference backend have not been
implemented in this repository.

## User journey

1. A developer installs JarvisCore:

   ```bash
   pip install jarviscore-framework
   ```

2. The developer visits:

   ```text
   https://jarviscore.developers.prescottdata.io/promo/
   ```

3. The developer registers and verifies their email address.

4. If promotional places remain, the site issues a unique token once.

5. The developer places the token in their environment:

   ```bash
   export JARVISCORE_PROMO_TOKEN="jc_trial_..."
   ```

6. Existing JarvisCore code automatically uses promotional inference:

   ```python
   from jarviscore.execution.llm import create_llm_client

   client = create_llm_client()
   response = await client.generate(
       prompt="Help me build my first JarvisCore agent"
   )
   print(response["content"])
   ```

No separate cloud SDK, CLI login, or provider API key is required.

## Architecture

```text
Developer
  │
  │ pip install + JARVISCORE_PROMO_TOKEN
  ▼
JarvisCore PromoLLMClient
  │
  │ HTTPS + Bearer jc_trial_...
  ▼
Developer-site promotional inference endpoint
  │
  │ server-side provider credential
  ▼
Approved upstream LLM
```

### Trust boundaries

- The public Python package is untrusted and contains no shared secret.
- The promotional token identifies one limited entitlement. It is not an
  upstream provider credential.
- The developer-site service owns provider credentials, eligibility, model
  selection, quotas, expiration, and the global campaign budget.
- All real enforcement happens on the server. Client-side checks are only for
  usability.

## What the library implements

### Promotional client

The client is located at:

```text
jarviscore/promo/client.py
```

It:

- activates when `JARVISCORE_PROMO_TOKEN` is configured;
- calls one fixed HTTPS endpoint that is not configurable;
- uses a fixed promotional model alias; the endpoint and alias are module
  constants, not constructor or configuration state;
- never sends a requested upstream model; the server alone selects it, and an
  explicit non-alias model request fails visibly;
- rejects responses that name any model other than the promotional alias;
- sends the token only in the `Authorization` header;
- never includes the token in the request body or raw call artifact;
- generates a stable `jcp_...` call ID for every request;
- validates the server response contract;
- exposes usage, tool calls, finish reason, entitlement state, and model;
- preserves the complete request and response locally;
- raises visible errors for invalid, expired, exhausted, or unavailable access;
- never silently falls through to a separately configured paid provider.

### Automatic provider selection

`UnifiedLLMClient` selects the promotion first when the token is present. If no
promotional token is configured, existing provider behavior is unchanged.

Promotional failures are terminal. This prevents an expired free entitlement
from unexpectedly causing charges through a developer's Azure, Claude, Gemini,
or other configured provider.

### Local call artifacts

Every promotional call is stored under:

```text
./traces/promo_calls/<call_id>.json
```

The directory can be changed with:

```bash
JARVISCORE_PROMO_RAW_ARTIFACT_DIR=/path/to/artifacts
```

The artifact contains the complete request payload, HTTP status, response
headers, and response body. The bearer token is excluded explicitly. Writes are
atomic and flushed to disk before the final file replaces the temporary file.

This behavior protects complete model and tool evidence from silent clipping.

### Health check

The existing command detects promotional configuration:

```bash
jarviscore check
```

It can make a real promotional inference request when asked:

```bash
jarviscore check --validate-llm
```

## What the developer site must implement

The site needs two small capabilities:

1. Registration and entitlement issuance.
2. A restricted inference endpoint.

### Registration

The page should live at:

```text
https://jarviscore.developers.prescottdata.io/promo/
```

The minimum flow is:

1. Collect an email address.
2. Apply CAPTCHA and registration rate limits.
3. Send an email-verification link.
4. Atomically claim one of the remaining promotional places.
5. Generate a cryptographically random `jc_trial_...` token.
6. Store only a secure token hash.
7. Display the original token once.
8. Show setup instructions and the promotion terms.

The first-X allocation must be transactional. Two concurrent registrations
must not be able to claim the same final place or exceed the campaign limit.

Suggested entitlement fields:

```text
id
verified_email_hash
token_hash
claimed_at
expires_at
input_tokens_used
output_tokens_used
request_count
status
```

### Inference endpoint

The Python package calls exactly:

```text
POST https://jarviscore.developers.prescottdata.io/api/promo/v1/generate
```

The complete request, response, and error schema is documented in:

```text
jarviscore/docs/reference/promotion-api.md
```

The server must:

- require `Authorization: Bearer jc_trial_...`;
- hash the presented token and find its entitlement;
- reject unknown, revoked, expired, or exhausted tokens;
- enforce request, token, concurrency, and campaign-level limits;
- use a fixed server-approved model or model allowlist;
- return only the promotional model alias, keeping the actual upstream
  deployment identity in private server telemetry;
- reject unsupported options instead of silently dropping them;
- echo the client-provided call ID;
- return complete content, tool calls, arguments, usage, and finish reason;
- hold all upstream provider credentials in server-side secret storage;
- avoid logging bearer tokens or prompt and response bodies;
- expose a campaign kill switch.

## Required response shape

A successful response must contain:

```json
{
  "call_id": "jcp_...",
  "content": "Complete model output",
  "tool_calls": [],
  "usage": {
    "input": 12,
    "output": 34,
    "total": 46
  },
  "model": "jarviscore-promo",
  "finish_reason": "stop",
  "entitlement": {
    "expires_at": "2026-09-30T00:00:00Z",
    "remaining_tokens": 999954
  }
}
```

An error response must contain a stable code and human-readable message:

```json
{
  "code": "quota_exhausted",
  "message": "Promotional allowance consumed"
}
```

Expected error codes are:

- `invalid_request`
- `unsupported_option`
- `invalid_token`
- `promotion_expired`
- `quota_exhausted`
- `rate_limited`
- `promotion_unavailable`

## Campaign limits

The team must decide the following before launch:

- number of eligible developers, X;
- registration opening and closing dates;
- entitlement duration;
- per-user token or monetary allowance;
- requests and tokens per minute;
- per-user concurrency;
- permitted model;
- maximum input and output sizes;
- total campaign spending ceiling;
- acceptable-use and privacy language.

Every entitlement should have both an expiration and a usage limit. A time-only
promotion is unsafe because one user could consume an unbounded amount during
the promotional period.

## Security requirements

The launch must satisfy these minimum controls:

- Never ship an upstream provider API key in the package, documentation,
  JavaScript, or registration response.
- Store only hashes of promotional tokens.
- Use HTTPS for registration, verification, and inference.
- Rate-limit registration, token verification, and inference separately.
- Do not place tokens in URLs, query strings, analytics, or logs.
- Do not accept arbitrary upstream endpoints or models from the client.
- Validate request sizes before reading or forwarding large payloads.
- Reserve estimated usage atomically before an upstream call and reconcile it
  with actual provider usage afterward.
- Enforce a global budget independently of per-user quotas.
- Provide immediate token revocation and a campaign-wide kill switch.
- Tell developers that prompts are processed by Prescott and the selected
  upstream model provider.

## Privacy and observability

The developer-site page must state:

- what account information is collected;
- that prompts and model responses pass through Prescott infrastructure;
- which upstream provider processes the request;
- content-retention and deletion behavior;
- whether content is used for training;
- how developers can report abuse or request deletion.

Operational telemetry should record call ID, token hash or entitlement ID,
status, latency, model, and usage. It should not record the bearer token, prompt
body, model output, or tool arguments.

## Testing already completed

The library tests cover:

- automatic promotional-provider detection;
- the fixed HTTPS endpoint;
- bearer authentication without placing the token in the payload;
- token redaction from network errors and artifacts;
- complete large-response preservation;
- preservation of tail evidence, tool calls, relation labels, and ranked
  entities;
- response and usage validation;
- durable error-response artifacts;
- terminal expiration and quota failures without paid-provider fallback;
- a fixed, non-configurable HTTPS endpoint;
- a fixed, non-configurable model alias (constructor and configuration
  overrides are rejected);
- kernel tier routing resolving every tier to the alias during promotional
  access;
- visible failure of explicit non-alias model requests;
- rejection of responses exposing a real upstream model name.

At implementation time, the relevant suites reported:

```text
13 promotional client tests passed
16 LLM fallback tests passed, 4 credential-dependent provider tests skipped
6 CLI scaffold tests passed
63 kernel tests passed
```

## Developer-site acceptance checklist

The developer-site work is ready when all of the following are true:

- [ ] `/promo/` explains the offer, limits, privacy terms, and setup.
- [ ] Email verification is required before allocation.
- [ ] First-X allocation is atomic and idempotent.
- [ ] Tokens are random, displayed once, and stored only as hashes.
- [ ] `/api/promo/v1/generate` matches the documented contract exactly.
- [ ] The server echoes `call_id` and returns complete evidence.
- [ ] Expiry, usage, rate, concurrency, model, and global-budget limits are
      enforced server-side.
- [ ] Provider credentials exist only in server-side secret storage.
- [ ] Prompt, response, and token bodies are absent from operational logs.
- [ ] Revocation and campaign kill-switch behavior have been tested.
- [ ] `jarviscore check --validate-llm` succeeds using a real test entitlement.
- [ ] Expired and exhausted test tokens return the documented errors.
- [ ] GTM copy says “first X verified developers,” not “first X downloads.”

## Ending the promotion

Old JarvisCore releases remain installable from PyPI, so the campaign cannot be
ended by deleting client code alone. Expiration must be enforced by the server.

At the end of the campaign:

1. Stop accepting new registrations.
2. Allow or revoke existing entitlements according to the published terms.
3. Return `promotion_expired` or `promotion_unavailable` clearly.
4. Remove promotional onboarding from the developer site.
5. Remove the temporary provider from a later JarvisCore release.
6. Keep the endpoint safely disabled for older package versions.

## Code map

| Area | Location |
|---|---|
| Promotional HTTP client | `jarviscore/promo/client.py` |
| Public promo exports | `jarviscore/promo/__init__.py` |
| Unified provider selection | `jarviscore/execution/llm.py` |
| Environment settings | `jarviscore/config/settings.py` |
| Health check | `jarviscore/cli/check.py` |
| Minimal environment template | `jarviscore/data/.env.minimal` |
| Full environment template | `jarviscore/data/.env.example` |
| Backend API contract | `jarviscore/docs/reference/promotion-api.md` |
| Regression tests | `tests/test_promo_client.py` |

## Ownership boundary

The public JarvisCore repository owns the client behavior and API contract.

The developer-site/backend system owns registration, eligibility, entitlement
storage, token issuance, provider credentials, inference, usage accounting,
abuse controls, campaign budgets, and campaign shutdown.
