ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

# "Book a call with Sam": the address is in the person's own mail. This reads who they
# write with under a name, so nobody has to be asked for an address the mailbox holds.

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

_READ = 20  # messages looked at
_ROBOT = r"(no-?reply|notifications?|mailer-daemon|do-?not-?reply|bounce)[^@]*@"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


async def gmail_find_correspondents(name: str) -> dict:
    """Find the email address of someone the person writes with, from a name or part
    of one ("Sam", "Rivera", "riv"). Looks at the most recent mail to, from or
    copying a person of that name.

    Returns `people`, most-written-with first: each with `name` (as their mail shows
    it), `email`, `messages` (how many of the recent messages they were on) and `last`
    (the date of the newest). The person's own address is left out, and an address
    that only sends notifications in someone's name (a no-reply address) comes last with
    `automated` true: it is not theirs to write to. When exactly one
    person fits, use that address and say which you used; when several fit, ask which;
    when none does, say the mail holds nobody of that name.
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
    """
    import re
    from email.utils import getaddresses

    words = [w.lower() for w in str(name or "").replace('"', " ").split()]
    if not words:
        return {"success": False, "data": None, "error": "a name, or part of one, is needed"}
    term = " ".join(words)
    listed = await nexus_call(  # noqa: F821
        "GET",
        f"{_BASE}/messages",
        params={"q": f"from:({term}) OR to:({term}) OR cc:({term})", "maxResults": _READ},
    )
    if not listed["ok"]:
        return {"success": False, "data": None,
                "error": f"the mail could not be searched: {_reason(listed)}"}
    own = await nexus_call("GET", f"{_BASE}/profile")  # noqa: F821
    me = str((own.get("json") or {}).get("emailAddress") or "").lower() if own["ok"] else ""
    people = {}
    for each in (listed["json"] or {}).get("messages") or []:
        got = await nexus_call(  # noqa: F821
            "GET",
            f"{_BASE}/messages/{each.get('id')}",
            params={"format": "metadata", "metadataHeaders": ["From", "To", "Cc", "Date"]},
        )
        if not got["ok"]:
            continue
        headers = {h.get("name", "").lower(): h.get("value", "")
                   for h in ((got["json"] or {}).get("payload") or {}).get("headers") or []}
        on_it = getaddresses([headers.get("from", ""), headers.get("to", ""),
                              headers.get("cc", "")])
        seen = set()
        for shown, address in on_it:
            address = address.strip().lower()
            if not address or address == me or address in seen:
                continue
            # a word of the name must begin a word of theirs: "sam" is Sam and Samuel,
            # not flotsam.org
            theirs = [t for t in re.split(r"[^a-z0-9]+", f"{shown} {address}".lower()) if t]
            if not all(any(t.startswith(w) for t in theirs) for w in words):
                continue
            seen.add(address)
            person = people.setdefault(
                address, {"name": "", "email": address, "messages": 0, "last": ""})
            if re.search(_ROBOT, address):
                person["automated"] = True  # a notification sent in their name, not them
            person["messages"] += 1
            person["name"] = person["name"] or shown.strip()
            person["last"] = person["last"] or headers.get("date", "")  # newest comes first
    found = sorted(
        people.values(), key=lambda p: (bool(p.get("automated")), -p["messages"]))[:10]
    out = {"people": found, "count": len(found), "looked_at": "the newest "
           f"{_READ} messages to, from or copying {term!r}"}
    if not found:
        out["note"] = f"No one named {term!r} is on the person's recent mail."
    return {"success": True, "data": out, "error": None}
