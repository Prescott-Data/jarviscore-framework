---
title: "Microsoft Graph read-only atoms"
description: "OneDrive metadata, Outlook pages, and original message/attachment bytes through injected Nexus calls."
---

# Microsoft Graph read-only atoms

These standalone atoms belong to the existing **`msgraph` SDK bundle**. The
canonical Nexus provider identifier is **`microsoft-graph`**, recorded in
[Nexus provider_names.md](https://github.com/Prescott-Data/nexus-framework/blob/fef5253b9056375cd3b3cf92ac293d95613b8595/provider_names.md).
The host catalogue derives `graph.microsoft.com` for both identifiers from the
same bundle. This is a destination catalogue entry, **not** a connection alias,
provider acceptance result, permission grant, or authentication implementation.
The caller must supply a correctly bound native Nexus connection; credentials
are accessible exclusively to the injected `nexus_call`, never to these atoms.

All operations are HTTP **GET**, with native `read` policy and no approval
requirement. Each file is independently executable through the shipped atom
contract; it has no dependency on another atom's namespace.

## Operations

All paths below are relative to `https://graph.microsoft.com/v1.0`.

| Atom | Endpoint / inputs |
| --- | --- |
| `msgraph_get_drive_item` | `/me/drive/items/{item_id}`; optional `drive_id` selects `/drives/{drive_id}` instead of `/me/drive` |
| `msgraph_list_drive_children` | `/me/drive/root/children` by default; `folder_id` selects `/items/{folder_id}/children`; optional `drive_id` |
| `msgraph_list_mail_folders` | `/me/mailFolders`; optional `parent_folder_id` selects `/me/mailFolders/{id}/childFolders`; `include_hidden=False` by default |
| `msgraph_list_messages` | `/me/messages`; optional `folder_id` selects `/me/mailFolders/{id}/messages` |
| `msgraph_get_message` | `/me/messages/{message_id}`; selected metadata plus the full Graph `body` object |
| `msgraph_list_message_attachments` | `/me/messages/{message_id}/attachments`; selected attachment metadata only |
| `msgraph_get_message_attachment` | `/me/messages/{message_id}/attachments/{attachment_id}`; selected metadata only |
| `msgraph_download_message_attachment` | `/me/messages/{message_id}/attachments/{attachment_id}/$value`; original Graph bytes |
| `msgraph_download_message` | `/me/messages/{message_id}/$value`; original Graph MIME bytes |

Identifiers are encoded as individual path segments, not interpreted as URLs
or paths. The default drive is the connected user's drive. All Outlook
operations use the connected user's mailbox; these atoms do not select another
user or implement application-permission `/users/{id}` retrieval.

## Return and pagination contracts

Every result has `success`, `data`, and `error`. Successful results have
`error=None`. Failures have `success=False` and `data=None`; HTTP failures
include the status, but never the raw provider body, headers, exception text,
or redirect location.

Metadata is allowlisted using `$select` and response projection. Drive facets
retain MIME type, folder child count, and parent identifiers. Outlook metadata
retains message identities, recipients, dates, and attachment flags; individual
message reads additionally retain `body`. Attachment metadata retains IDs,
names, types, sizes, inline flags, dates, and recognized `@odata.type` values.
No metadata result exposes `@microsoft.graph.downloadUrl`, `webUrl`, attachment
`sourceUrl`, `contentBytes`, authorization fields, or bearer/presigned URLs.
These metadata operations are not full-fidelity Graph JSON exports.

Every **listing** has `page_size=100` (integer, 1–1000) and
`continuation_cursor=""`. One invocation retrieves exactly one provider page:

```python
{
    "success": True,
    "data": {
        "items": [{"id": "provider-id"}],
        "continuation_cursor": "https://graph.microsoft.com/v1.0/me/messages?$skip=100",
        "has_more": True,
    },
    "error": None,
}
```

Treat the cursor as opaque. Replay it **unchanged** into the same atom with the
same drive/folder/message identifiers until `has_more=False` and
`continuation_cursor=None`. All entries in each returned page are preserved;
`page_size` does not slice or truncate a provider response. Continuation calls
use the entire Graph `@odata.nextLink` with no reconstructed skip token or added
query parameters. Cursors must use the exact Graph HTTPS host and original
collection path, without userinfo, ports, fragments, or credential query keys.
Malformed pages/cursors fail explicitly rather than reporting an empty or
complete listing. No automatic page accumulation or silent result cap exists.

Downloads return a JSON-safe, lossless representation:

```python
{"success": True, "data": {"content_base64": "AP8=", "byte_count": 2}, "error": None}
```

Base64 decoding recovers the exact `response["content"]` bytes, including empty
files and non-UTF-8 values. Both direct bytes and the shipped sandbox RPC's exact
`{"__bytes__": "base64"}` envelope are supported with strict decoding. There is no text fallback or decode/re-encode of the
original payload. Attachment `$value` is supported for **file** and **item**
attachments. A **reference** attachment has no direct original download here;
Graph's failure (normally HTTP 405) is returned, not bypassed by following its
source URL. Item attachments use Graph's raw representation (such as MIME),
not an invented export format.

## Explicit remaining gates

- **OneDrive original download is blocked.** Graph
  [driveItem `/content`](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0)
  redirects to a preauthenticated download URL. A credential-bound native
  primitive that consumes the redirect privately and retrieves the original
  without exposing the URL or forwarding credentials is missing. No OneDrive
  download atom is offered; raw HTTP, custom OAuth, expanded download-host
  allowances, and blanket `follow_redirects` are not substitutes.
- **Live provider acceptance is unverified.** Tests use injected Nexus response
  fixtures, not a tenant connection. Live connection/bundle identity binding,
  delegated consent, folder-specific nextLink shapes, permissions, throttling,
  and response bytes across deployed Nexus modes remain integration gates.
  Read requirements in the Graph contracts are `Files.Read` for delegated
  OneDrive reads and `Mail.Read` for message bodies/attachments. No scopes or
  scope authority are changed here.
- The pre-existing `msgraph` provider seed is labeled `verified`; this change
  does not promote or edit that label. Its seed machinery may inherit that
  label for newly discovered operations. That inherited label is **not**
  evidence of a live run of these new atoms; per-operation acceptance tracking
  is outside this bounded atom/host-catalogue change.

## Verified endpoint references

- [driveItem metadata](https://learn.microsoft.com/en-us/graph/api/driveitem-get?view=graph-rest-1.0)
  and [children](https://learn.microsoft.com/en-us/graph/api/driveitem-list-children?view=graph-rest-1.0)
- [Mail folders](https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders?view=graph-rest-1.0)
  and [child folders](https://learn.microsoft.com/en-us/graph/api/mailfolder-list-childfolders?view=graph-rest-1.0)
- [Message listing and entire-nextLink pagination](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)
  and [message metadata/MIME](https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0)
- [Attachment listing](https://learn.microsoft.com/en-us/graph/api/message-list-attachments?view=graph-rest-1.0)
  and [attachment metadata/raw values](https://learn.microsoft.com/en-us/graph/api/attachment-get?view=graph-rest-1.0)
