---
icon: material/gift
---

# Launch Promotion API Contract

This contract is the only developer-site backend required by the temporary
JarvisCore launch promotion. The Python client uses a fixed endpoint:

```text
POST https://jarviscore.developers.prescottdata.io/api/promo/v1/generate
```

## Authentication

The endpoint requires `Authorization: Bearer <token>`, where the token is the
unique `jc_trial_...` entitlement issued after registration. The token is a
Prescott promotion credential, not an upstream LLM API key.

The server must hash stored tokens, enforce HTTPS, and apply expiration, quota,
rate, concurrency, model, request-size, and global campaign-spend limits before
calling the upstream model.

## Request

```json
{
  "call_id": "jcp_...",
  "model": "jarviscore-promo",
  "messages": [{"role": "user", "content": "Hello"}],
  "temperature": 0.7,
  "max_tokens": 4000,
  "requested_model": "gpt-4o",
  "options": {
    "response_format": {"type": "json_object"}
  }
}
```

`model` is the fixed promotional model alias. `requested_model` preserves the
framework's internal routing request as evidence; it does not authorize that
model. The server chooses the permitted upstream deployment. It must either
honor each field in `options` or reject the request with `unsupported_option`;
it must not silently omit request arguments.

The server must use and echo the supplied `call_id`.

## Successful response

```json
{
  "call_id": "jcp_...",
  "content": "Complete model output",
  "tool_calls": [],
  "usage": {"input": 12, "output": 34, "total": 46},
  "model": "actual-server-selected-model",
  "finish_reason": "stop",
  "entitlement": {
    "expires_at": "2026-09-30T00:00:00Z",
    "remaining_tokens": 999954
  }
}
```

Every required field must be present. `content`, `tool_calls`, tool arguments,
usage, relation labels, ranked entities, and other evidence must be complete.
The server must never clip a completed upstream response. If a provider or
transport limit prevents completion, return a visible error or a non-`stop`
`finish_reason`; never present partial content as complete.

The client stores the complete request, status, response headers, and response
body in a durable local artifact under `./traces/promo_calls/<call_id>.json`.
The bearer token is intentionally excluded and this omission is declared in
the artifact.

## Error response

```json
{
  "code": "quota_exhausted",
  "message": "Promotional allowance consumed"
}
```

Supported error codes:

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `invalid_request` | Request failed schema validation |
| 400 | `unsupported_option` | The server cannot honor a supplied option |
| 401 | `invalid_token` | Token is missing, malformed, or unknown |
| 403 | `promotion_expired` | Entitlement has expired or the campaign ended |
| 402 | `quota_exhausted` | Included usage has been consumed |
| 429 | `rate_limited` | Per-token or campaign rate limit reached |
| 503 | `promotion_unavailable` | Promotional inference is temporarily unavailable |

Errors are terminal in the Python client. JarvisCore never silently falls
through to a separately configured paid provider.

## Registration dependency

The developer site must verify an email and atomically allocate one of the
first-X entitlements before showing the token once. Registration and token
issuance are deliberately outside the public library.
