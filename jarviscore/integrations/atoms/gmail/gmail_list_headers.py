ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

# gmail_list_messages returns Gmail's list payload, which is ids only, so a triage ("what
# came in since yesterday evening") needs gmail_get_message per id, and each of those is
# the whole message, body and all. This read returns what triage needs and nothing more:
# Gmail's metadata format with a few headers and the snippet, one small record per message.

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_HEADERS = ("From", "To", "Cc", "Subject", "Date", "List-Unsubscribe")


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


async def _named(messages: list) -> None:
    """Replace Gmail's ids for the person's own labels (Label_12) with their names, as
    the person sees them. System labels (INBOX, UNREAD) are their own names already.
    One read of the label list, and only when a message carries a label of theirs."""
    if not any(str(i).startswith("Label_") for m in messages for i in m.get("labels") or []):
        return
    listed = await nexus_call("GET", f"{_BASE}/labels")  # noqa: F821
    if not listed["ok"]:
        return  # the ids stay; the read itself did not fail
    names = {x.get("id"): x.get("name") for x in (listed["json"] or {}).get("labels") or []}
    for m in messages:
        m["labels"] = [names.get(i, i) for i in m.get("labels") or []]


async def gmail_list_headers(query: str = "", max_results: int = 20,
                             page_token: str = "") -> dict:
    """List messages with their headers and snippet, no bodies: for each message Gmail's
    `q` search matches (the same syntax as the search box, e.g. `newer_than:1d
    -category:promotions`, `is:unread`, `from:sam@example.com`, `label:deals`,
    `after:2026/11/01 before:2026/11/15`, `has:attachment`), newest first: id, thread_id,
    labels (by name), from, to, cc, subject, date,
    snippet, and `unsubscribe` (true for list mail, from its List-Unsubscribe header).
    `id` is the message (gmail_get_message reads it, gmail_draft_reply answers it);
    `thread_id` is its conversation (gmail_read_thread reads it, gmail_triage_threads and
    gmail_trash_threads act on it). `max_results` is 1 to 50. When the answer has
    `next_page_token` there is more mail that matches: call again with it as `page_token`."""
    params = {"maxResults": max(1, min(int(max_results), 50))}
    if query and query.strip():
        params["q"] = query.strip()
    if page_token:
        params["pageToken"] = page_token
    listed = await nexus_call("GET", f"{_BASE}/messages", params=params)  # noqa: F821
    if not listed["ok"]:
        return {
            "success": False,
            "data": None,
            "error": f"the mail could not be listed: {_reason(listed)}",
        }
    ids = [m.get("id") for m in (listed["json"] or {}).get("messages") or [] if m.get("id")]
    messages = []
    for message_id in ids:
        got = await nexus_call(  # noqa: F821
            "GET",
            f"{_BASE}/messages/{message_id}",
            params={"format": "metadata", "metadataHeaders": list(_HEADERS)},
        )
        if not got["ok"]:
            messages.append({"id": message_id, "error": _reason(got)})
            continue
        payload = got["json"] or {}
        headers = {
            h.get("name", "").lower(): h.get("value", "")
            for h in (payload.get("payload") or {}).get("headers") or []
        }
        messages.append(
            {
                "id": payload.get("id", message_id),
                "thread_id": payload.get("threadId"),
                "labels": payload.get("labelIds") or [],
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                **({"cc": headers["cc"]} if headers.get("cc") else {}),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "snippet": payload.get("snippet", ""),
                "unsubscribe": bool(headers.get("list-unsubscribe")),
            }
        )
    await _named(messages)
    data = {
        "messages": messages,
        "result_size_estimate": (listed["json"] or {}).get("resultSizeEstimate"),
    }
    if (listed["json"] or {}).get("nextPageToken"):
        data["next_page_token"] = listed["json"]["nextPageToken"]
    return {"success": True, "data": data, "error": None}
