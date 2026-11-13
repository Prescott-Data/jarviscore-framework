# Credential-bound original downloads

`NexusCallProxy.call(..., original_download=True)` is an explicit native GET-only
original-byte mode. The injected `nexus_call` accepts the same opt-in. It does not
create a second credential path: normal operation contracts, provider host binding,
organisation resource scopes and the acting person's authority apply to the initial
API request, before any credential lookup or I/O. Configure provider-wide
`request_path` limits for selected originals; narrowly matched rules alone do not
close unmatched-endpoint gaps. The existing native contract rules are unchanged:
verified model/registry contracts constrain initial method/path; shipped atoms
retain the native declared-effect and scope checks.

```python
response = await nexus_call(
    "GET", "https://api.box.com/2.0/files/12345/content",
    original_download=True, max_bytes=8 * 1024 * 1024,
)
if response["ok"]:
    original = response["content"]  # Lossless bytes, including empty files.
```

## Trusted configuration

Only an operator configuring the native runtime may supply redirect download
hosts. No download-host defaults are enabled. `NEXUS_ORIGINAL_DOWNLOAD_HOSTS` is a
JSON provider-to-exact-DNS-host list in process settings, for example:

```json
{"box": ["dl.boxcloud.com"]}
```

Alternatively construct the native proxy with trusted configuration:

```python
proxy = NexusCallProxy(
    authentication_manager,
    original_download_hosts={"box": ["dl.boxcloud.com"]},
)
```

The configuration is copied at construction. Neither caller/model kwargs nor
request-supplied allowlists can change it. Wildcards, suffix matching, URLs, IP
literals and ports are not accepted. Never derive this configuration automatically
from a `Location` or `@microsoft.graph.downloadUrl`, nor accept it from an agent
payload. Provision independently verified exact content hosts for each deployment;
an unrecognised CDN or tenant hostname fails closed. This setting permits only
credential-free continuations, not credential placement on those hosts.

## Vendor behavior and provider gating

Verified against official documentation on 2026-11-13 (not live OAuth acceptance):

- [Box download guide](https://developer.box.com/guides/downloads/file/) documents
  `GET https://api.box.com/2.0/files/:id/content`, a 302 response and the example
  `https://dl.boxcloud.com/d/1/[long-random-string]/download`. The URL expires;
  Box also documents `Retry-After` when a file is not ready. The example does not
  establish that every Box deployment uses that exact hostname.
- [Microsoft Graph driveItem content](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0)
  documents a 302 to a short-lived preauthenticated URL, explicitly requiring no
  `Authorization` at the destination. Its example host is
  `b0mpua-by3301.files.1drv.com`, not a universal allowlist. Other tenants/CDNs must
  be independently verified and configured by exact hostname; no `*.1drv.com` or
  `*.sharepoint.com` permission is granted.

The canonical corpus currently contains Box metadata/upload atoms, but no Box
original-download atom and no OneDrive atom namespace. No existing atom was
rewired or renamed. Existing `msgraph` mail `$value` atoms and Dropbox POST
download behavior are unchanged. This GET primitive does not enable Dropbox POST
redirect downloads. It does not establish that `microsoft-graph` and `msgraph`
name the same broker provider. Operator configuration must use the provider
actually bound to the opaque connection; no alias is inferred.

## Boundary guarantees

- Default byte limit: 16 MiB; caller may reduce or raise it up to the hard 64 MiB
  ceiling. The entire transfer, credential lookup and refresh share a bounded
  timeout (default 30 seconds, maximum 300). Bodies stream inside Nexus; oversized,
  compressed or failed responses yield no partial bytes. `Accept-Encoding` is
  forced to `identity` and unexpected content encodings are rejected.
- At most three manual redirects. Only one absolute, unambiguous HTTPS `Location`
  per response is accepted; userinfo, fragments, nonstandard ports and unknown
  hosts are rejected. Redirects back to any credential-bearing provider API host
  are rejected even if accidentally operator-allowlisted. A continuation is a
  capability issued by the authorized initial resource server, not independently
  chosen model intent; path scopes are not broadened to arbitrary CDN requests.
- Initial credentials come from the selected native authentication manager only.
  Broker failures/refusals never fall back to another credential store. A 401 on
  the initial source may refresh that same connection once, under the original
  operation identity. A 401 at a signed destination never refreshes or receives
  credentials.
- Dedicated clients disable environment proxies and automatic redirects. Explicit
  `httpx.Request` objects bypass client default cookies, headers and auth. Redirect
  requests receive only generated Host, Accept and Accept-Encoding headers; no
  original selectors, credential headers, cookies or query params are copied.
  Locations containing the resolved credential values are rejected.
- Success returns `content` bytes, empty `body`, `json=None`, and only validated
  MIME type/numeric length or retry metadata. Location, Set-Cookie, disposition and
  arbitrary provider headers are never returned. Failures discard provider bodies
  and headers and use an opaque message; signed URLs are not embedded in exceptions.
  Native journals record only the initial intent and status outcome. Context-local
  filtering suppresses httpx/httpcore URL/header logs during this private transport,
  without suppressing unrelated concurrent provider calls.

Unsupported hosts, ambiguous redirects and unsupported providers remain gated.
Native mock-transport tests verify the boundary; they are not a claim of live
provider consent, token refresh or end-to-end provider acceptance.
