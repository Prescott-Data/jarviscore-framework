ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": [
        "thread_ids", "archive", "mark", "star", "add_labels", "remove_labels",
    ],
    "consequence": (
        "Archives, labels, stars or marks read the listed Gmail conversations. Nothing is "
        "deleted or sent, and each change can be undone in Gmail."
    ),
}

# Tidying the inbox: one call for many conversations, and no approval, because every
# change here is one the person can undo in Gmail and none leaves the mailbox. It acts on
# conversations, not messages: Gmail shows a conversation in the inbox while any one
# message in it is there, so archiving a single message left the conversation where it was.

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

_MOST = 50  # conversations in one call
_SYSTEM = {"INBOX", "UNREAD", "STARRED", "IMPORTANT"}
# Not tidying, and so not for a tool that runs without approval: Spam teaches Gmail about
# the sender, Trash deletes in thirty days (gmail_trash_threads asks), and Sent and
# Draft say what a message is. Named here, they are refused; a label of the
# person's own that happens to be called one of these cannot be reached this way.
_NOT_HERE = {"SPAM", "TRASH", "SENT", "DRAFT"}


def _names(spec) -> list:
    if isinstance(spec, (list, tuple)):
        spec = ",".join(str(s) for s in spec)
    return [n.strip() for n in str(spec or "").split(",") if n.strip()]


async def _label_ids(names: list) -> tuple:
    """Gmail's ids for labels named as the person sees them, without regard to case. A
    label that does not exist is refused by name: making one is its own act."""
    ids = [n.upper() for n in names if n.upper() in _SYSTEM]
    wanted = [n for n in names if n.upper() not in _SYSTEM]
    if not wanted:
        return ids, None
    listed = await nexus_call("GET", f"{_BASE}/labels")  # noqa: F821
    if not listed["ok"]:
        return [], f"labels could not be listed: {_reason(listed)}"
    by_name = {
        (label.get("name") or "").lower(): label.get("id")
        for label in (listed["json"] or {}).get("labels") or []
    }
    for name in wanted:
        found = by_name.get(name.lower())
        if not found:
            return [], f"no label named {name!r}; create it first with gmail_create_label"
        ids.append(found)
    return ids, None


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


async def gmail_triage_threads(
    thread_ids: list,
    archive: bool = False,
    mark: str = "",
    star: str = "",
    add_labels: str = "",
    remove_labels: str = "",
) -> dict:
    """Tidy conversations in the person's Gmail, as many as 50 in one call: archive
    them, mark them read or unread, star or unstar them, add or remove labels. It runs
    without an approval request: nothing is deleted or sent, and every change can be undone.

    `thread_ids` are the `thread_id` of each conversation, from gmail_list_headers. Every
    message of each conversation is changed. `archive` true takes them out of the inbox
    (they stay in All Mail). `mark` is "read" or "unread". `star` is "star" or "unstar".
    `add_labels` and `remove_labels` are label names as the person sees them,
    comma-separated, matched without regard to case; a label must exist already
    (gmail_list_labels shows them, gmail_create_label makes one). Pass everything that
    should happen to these conversations in the one call.

    Returns `changed` (how many), `did` (what was done, in words) and `failed`: the
    conversations Gmail refused, each with its reason. Report the failures.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads/modify
    """
    ids = list(dict.fromkeys(str(t).strip() for t in (thread_ids or []) if str(t).strip()))
    if not ids:
        return {"success": False, "data": None, "error": "thread_ids: at least one is needed"}
    if len(ids) > _MOST:
        return {"success": False, "data": None,
                "error": f"at most {_MOST} conversations in one call; {len(ids)} were given"}
    mark, star = str(mark or "").strip().lower(), str(star or "").strip().lower()
    if mark not in ("", "read", "unread") or star not in ("", "star", "unstar"):
        return {"success": False, "data": None,
                "error": 'mark is "read" or "unread"; star is "star" or "unstar"'}
    adding, removing = _names(add_labels), _names(remove_labels)
    did = []
    if archive is True:
        removing.append("INBOX")
        did.append("archived")
    if mark:
        (removing if mark == "read" else adding).append("UNREAD")
        did.append(f"marked {mark}")
    if star:
        (adding if star == "star" else removing).append("STARRED")
        did.append("starred" if star == "star" else "unstarred")
    did += [f"labelled {n}" for n in _names(add_labels)]
    did += [f"label {n} removed" for n in _names(remove_labels)]
    if not adding and not removing:
        return {"success": False, "data": None,
                "error": "nothing to do: pass archive, mark, star or a label"}
    barred = sorted({n.upper() for n in adding + removing} & _NOT_HERE)
    if barred:
        return {"success": False, "data": None,
                "error": f"{', '.join(barred)} cannot be set here: this tool only tidies. "
                         "Deleting is gmail_trash_threads, which asks the person."}
    both = {n.lower() for n in adding} & {n.lower() for n in removing}
    if both:
        return {"success": False, "data": None,
                "error": f"asked both to add and to remove: {', '.join(sorted(both))}"}
    add_ids, error = await _label_ids(adding)
    if error:
        return {"success": False, "data": None, "error": error}
    remove_ids, error = await _label_ids(removing)
    if error:
        return {"success": False, "data": None, "error": error}
    body = {}
    if add_ids:
        body["addLabelIds"] = add_ids
    if remove_ids:
        body["removeLabelIds"] = remove_ids
    changed, failed = [], []
    for thread_id in ids:
        done = await nexus_call(  # noqa: F821
            "POST",
            f"{_BASE}/threads/{thread_id}/modify",
            headers={"Content-Type": "application/json"},
            json=body,
        )
        if done["ok"]:
            changed.append(thread_id)
        else:
            failed.append({"thread_id": thread_id, "error": _reason(done)})
    if not changed:
        return {"success": False, "data": None,
                "error": f"none of the {len(ids)} conversations was changed: "
                         f"{failed[0]['error']}"}
    return {
        "success": True,
        "data": {"changed": len(changed), "did": did, "failed": failed},
        "error": None,
    }
