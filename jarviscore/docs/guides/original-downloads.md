# Credential-bound original downloads

`NexusCallProxy.call(..., original_download=True, max_bytes=16777216)` is an
explicit native original-byte mode. GET is supported; POST is restricted to the
verified native read contract for Dropbox's direct `/2/files/download` endpoint,
and **every POST redirect is refused**. The injected `nexus_call` accepts the same
opt-in. It does not create a second credential path: normal operation contracts,
provider host binding,
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
JSON provider-to-exact-DNS-host list in the trusted settings field
`nexus_original_download_hosts`, for example:

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
- [Google Drive download guide](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
  documents original **blob** reads through `files.get` with `alt=media`. Workspace
  document exports and Google Vids long-running downloads are different operations
  and are not synthesized by this atom. Direct original reads need no redirect
  allowlist; any unexpected redirect still fails closed unless independently
  verified and operator-configured.
- [Dropbox file download reference](https://docs.dropboxapi.com/dropbox-api/api-reference/user-endpoints/files/download)
  documents `POST https://content.dropboxapi.com/2/files/download` as a
  **content-download**, requiring `files.content.read`, with JSON selectors in
  `Dropbox-API-Arg` and a direct binary 200 response. Non-ASCII/control characters
  are JSON-escaped, preserving the selector exactly. This reviewed read endpoint
  is the sole supported original POST. Native shipped/runtime origin, declared
  `read`, and a verified matching operation contract are all mandatory, even
  with policy enforcement disabled; a model/registry read claim cannot authorize
  POST. Generic mutation policy is unchanged. All POST redirects are refused,
  including operator-allowlisted destinations.

## Registry-first file original atoms

| Canonical SDK atom | Inputs |
| --- | --- |
| `box_download_file` (`box`) | `file_id`, optional `destination_path=""`, `max_bytes=16777216` |
| `msgraph_download_drive_item` (`msgraph`) | `item_id`, optional `drive_id=""`, `destination_path=""`, `max_bytes=16777216` |
| `google_drive_download_file` (`google_drive`) | `file_id`, required `destination_path`, optional `max_bytes=16777216` |
| `dropbox_download_file` (`dropbox`) | `dropbox_path`, required `destination_path`, optional `max_bytes=16777216` |

Each canonical file is seeded by the existing registry discovery mechanism and
has native `read`/`never` policy plus a verified endpoint contract. No raw HTTP,
credential access, download URL output, or independently widened host permissions
exist in these atoms. IDs are encoded as individual segments; Dropbox selectors
retain lossless ASCII JSON serialization. Server-selected original-resource scopes
must still be granted. Unsupported hosts/providers remain gated.

Box and Graph return `data.content_base64` and `data.byte_count`, plus the chosen
`data.destination_path` only when saving. Base64 preserves empty and non-UTF-8
originals; strict native `{"__bytes__": "base64"}` RPC envelopes are supported,
never text fallbacks. Existing Drive/Dropbox result shapes are retained:
`data={"destination_path": ..., "bytes": ...}` (Drive also retains top-level
`file_id`). Raw errors, provider filenames/headers, and signed URLs are not returned.

Box/Graph destinations must be safe, relative native output paths. Drive/Dropbox
retain direct-call absolute path support; in the sandbox an absolute destination
must belong to its injected native `output_dir`, while relative paths are rooted
there. Caller-chosen Unicode/nested names are allowed. Empty segments, traversal,
absolute Box/Graph paths, backslashes, control characters, and colon-based paths
are rejected before transfer. Files are created exclusively through directory
file descriptors with no symlink following; existing files/symlinks/hardlinks are
not overwritten. No directory/file is created before successful bounded-byte
validation. Partial file writes are removed on failure.

The native Coder registry path supplies the parent-side read operation grant and
operation identity. Its legacy `_mutation_authority` transport key also carries
reviewed read POST identity; this does **not** change the declared read effect or
permit arbitrary model POSTs. Do not fabricate grants in model code.

No OneDrive namespace or `microsoft-graph`/`msgraph` broker alias is introduced.
The new Graph atom explicitly uses the SDK's existing `msgraph` provider ID.
An operator must bind that opaque connection correctly and provision independently
verified exact redirect hosts under that ID. A catalogue entry for both spellings
is not proof of broker aliasing. Live tenant/consent/provider acceptance remains
unverified; inherited seed `verified` labels are not live acceptance evidence.

## Boundary guarantees

- Default byte limit: 16 MiB; caller may reduce or raise it up to the hard 64 MiB
  ceiling. The entire transfer, credential lookup and refresh share a bounded
  timeout (default 30 seconds, maximum 300). Bodies stream inside Nexus; oversized,
  compressed or failed responses yield no partial bytes. `Accept-Encoding` is
  forced to `identity` and unexpected content encodings are rejected.
- GET permits at most three manual redirects; POST permits none. Only one
  absolute, unambiguous HTTPS `Location` per response is accepted; userinfo,
  fragments, nonstandard ports and unknown
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
