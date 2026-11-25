ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _addresses(spec) -> list:
    """The email addresses in a comma-separated list (or a list), lower case, in order,
    each once. An entry with no address in it comes back as it was typed, so the caller
    can refuse it by name."""
    from email.utils import getaddresses

    if isinstance(spec, (list, tuple)):
        spec = ", ".join(str(s) for s in spec)
    found = []
    for _, address in getaddresses([str(spec or "")]):
        address = address.strip().lower()
        if address and address not in found:
            found.append(address)
    return found


def _bad(addresses: list) -> list:
    return [a for a in addresses if "@" not in a or " " in a or a.startswith("@")]


def _text(payload: dict) -> tuple:
    """A message's text and the names of its attachments: the plain part wherever it sits,
    or, for mail sent as HTML only, the HTML with its tags taken out."""
    import base64
    import html
    import re

    found, files, stack = {"text/plain": [], "text/html": []}, [], [payload or {}]
    while stack:
        part = stack.pop(0)
        stack[0:0] = part.get("parts") or []
        if part.get("filename"):
            files.append(part["filename"])
            continue
        kind = (part.get("mimeType") or "").lower()
        raw = (part.get("body") or {}).get("data") or ""
        if kind in found and raw:
            found[kind].append(
                base64.urlsafe_b64decode(raw + "==").decode("utf-8", errors="ignore"))
    body = "\n".join(found["text/plain"])
    if not body.strip() and found["text/html"]:
        page = "\n".join(found["text/html"])
        page = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", page)
        page = re.sub(r"(?i)<(br|/p|/div|/tr|/li|/h[1-6])\b[^>]*>", "\n", page)
        body = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [" ".join(line.split()) for line in body.replace("\r", "").split("\n")]
    kept = [line for i, line in enumerate(lines) if line or (i and lines[i - 1])]
    return "\n".join(kept).strip(), files


def _draft(draft: dict) -> dict:
    """A draft as the person would recognise it: who it goes to, its subject, how it
    begins, and its text with the line breaks taken out (what an approval request can be
    checked by)."""
    message = draft.get("message") or {}
    headers = {h.get("name", "").lower(): h.get("value", "")
               for h in (message.get("payload") or {}).get("headers") or []}
    text, files = _text(message.get("payload") or {})
    return {
        "draft_id": draft.get("id"),
        "thread_id": message.get("threadId"),
        "to": _addresses(headers.get("to")),
        "cc": _addresses(headers.get("cc")),
        "bcc": _addresses(headers.get("bcc")),
        "subject": " ".join((headers.get("subject") or "").split()),
        "is_reply": bool(headers.get("in-reply-to")),
        "text": " ".join(text.split()),
        "attachments": files,
    }


async def gmail_list_drafts(query: str = "", max_results: int = 10) -> dict:
    """List the drafts waiting in the person's Gmail, newest first: for each its
    `draft_id` (what gmail_send_draft takes), `to`, `cc`, `bcc`, `subject`, `is_reply`
    (whether it sits in a conversation), `opening` (its first 300 characters) and
    `length`. `query` narrows them with Gmail's search words (`to:sam`, `subject:invoice`).
    `max_results` is 1 to 20. Use it to find the draft a step asks you to send.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/list
    """
    params = {"maxResults": max(1, min(int(max_results or 10), 20))}
    if query and query.strip():
        params["q"] = query.strip()
    listed = await nexus_call("GET", f"{_BASE}/drafts", params=params)  # noqa: F821
    if not listed["ok"]:
        return {"success": False, "data": None,
                "error": f"the drafts could not be listed: {_reason(listed)}"}
    drafts = []
    for each in (listed["json"] or {}).get("drafts") or []:
        got = await nexus_call(  # noqa: F821
            "GET", f"{_BASE}/drafts/{each.get('id')}", params={"format": "full"})
        if not got["ok"]:
            drafts.append({"draft_id": each.get("id"), "error": _reason(got)})
            continue
        draft = _draft(got["json"] or {})
        text = draft.pop("text")
        drafts.append({**draft, "opening": text[:300], "length": len(text)})
    return {"success": True, "data": {"drafts": drafts, "count": len(drafts)}, "error": None}
