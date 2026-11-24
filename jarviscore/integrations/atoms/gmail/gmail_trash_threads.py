ATOM_POLICY = {
    "effect": "destructive",
    "approval": "required",
    "idempotency_fields": ["thread_ids", "subjects"],
    "consequence": (
        "Moves the listed Gmail conversations to the trash, where Gmail keeps them for 30 "
        "days before deleting them for good."
    ),
}

# "Delete" means the trash, never the permanent delete (gmail_delete_message, which Google
# refuses without the whole-mailbox scope). The call names each conversation's subject so
# the approval request can list them, and each is read first: when a subject is not that
# conversation's, nothing is moved.

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

_MOST = 25  # conversations in one approval request


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _same(a: str, b: str) -> bool:
    """Whether two subjects are the same but for capitals, spacing and Re:/Fwd: in front."""
    import re

    def bare(text):
        text = " ".join(str(text or "").lower().split())
        return re.sub(r"^((re|fwd?):\s*)+", "", text)

    return bare(a) == bare(b)


def _consequence(params: dict) -> str:
    """What the approval request says this call does, from its arguments alone."""
    subjects = [" ".join(str(s).split())[:70] for s in (params.get("subjects") or [])]
    count = len(params.get("thread_ids") or [])
    listed = "; ".join(f'"{s}"' for s in subjects[:12])
    more = f" and {len(subjects) - 12} more" if len(subjects) > 12 else ""
    noun = "conversation" if count == 1 else "conversations"
    return (f"Moves {count} Gmail {noun} to the trash: {listed}{more}. Gmail keeps them "
            "in Trash for 30 days, where they can be restored, then deletes them for good.")


async def gmail_trash_threads(thread_ids: list, subjects: list) -> dict:
    """Move conversations to the trash in the person's Gmail: this is what "delete"
    means here. Gmail keeps them in Trash for 30 days, where the person can restore
    them. It waits for the person's approval, which lists the subjects.

    `thread_ids` are the `thread_id` of each conversation, from gmail_list_headers, at most
    25. `subjects` are their subjects, one for each id in the same order, as listed there:
    they are what the approval request shows, and each is checked against its conversation. When one
    does not match, nothing is moved and the answer says which. Every message of each
    conversation goes.

    Returns `trashed` (how many) and `failed`: the conversations Gmail refused, each with
    its reason.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads/trash
    """
    ids = [str(t).strip() for t in (thread_ids or []) if str(t).strip()]
    titles = [str(s) for s in (subjects or [])]
    if not ids:
        return {"success": False, "data": None, "error": "thread_ids: at least one is needed"}
    if len(ids) != len(titles) or len(set(ids)) != len(ids):
        return {"success": False, "data": None,
                "error": "subjects must hold one subject for each thread id, in the same "
                         "order, and no id twice"}
    if len(ids) > _MOST:
        return {"success": False, "data": None,
                "error": f"at most {_MOST} conversations in one call; {len(ids)} were given"}
    for thread_id, title in zip(ids, titles, strict=True):
        got = await nexus_call(  # noqa: F821
            "GET",
            f"{_BASE}/threads/{thread_id}",
            params={"format": "metadata", "metadataHeaders": ["Subject"]},
        )
        if not got["ok"]:
            return {"success": False, "data": None,
                    "error": f"conversation {thread_id} could not be read, so nothing was "
                             f"moved: {_reason(got)}"}
        first = ((got["json"] or {}).get("messages") or [{}])[0]
        real = next((h.get("value", "") for h in (first.get("payload") or {}).get("headers")
                     or [] if h.get("name", "").lower() == "subject"), "")
        if not _same(real, title):
            return {"success": False, "data": None,
                    "error": f"conversation {thread_id} is {real!r}, not {title!r}; nothing "
                             "was moved. Pass each conversation's own subject."}
    trashed, failed = [], []
    for thread_id in ids:
        done = await nexus_call("POST", f"{_BASE}/threads/{thread_id}/trash")  # noqa: F821
        if done["ok"]:
            trashed.append(thread_id)
        else:
            failed.append({"thread_id": thread_id, "error": _reason(done)})
    if not trashed:
        return {"success": False, "data": None,
                "error": f"none of the {len(ids)} conversations was moved: "
                         f"{failed[0]['error']}"}
    return {
        "success": True,
        "data": {"trashed": len(trashed), "failed": failed,
                 "kept_in_trash_days": 30},
        "error": None,
    }
