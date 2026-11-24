"""The Gmail atoms that read: headers a page at a time, a conversation without its
quoting, the drafts, the labels, and who the person writes with."""

import base64
import email
import json

import pytest

from jarviscore.execution.atom_contract import SHIPPED_ATOMS_DIR, read_contract

SYSTEM = "gmail"
DIR = SHIPPED_ATOMS_DIR / SYSTEM
API = "https://gmail.googleapis.com/gmail/v1/users/me/"
ME = "owner@example.com"


def contract(name):
    """The shipped atom's source read against the contract."""
    return read_contract((DIR / f"{name}.py").read_text(encoding="utf-8"),
                         system=SYSTEM, expected_name=name)


def atom(name):
    result = contract(name)
    assert result.ok, result.report()
    return result.atom


def consequence(name, params):
    """What the atom says a call does, from its arguments (its `_consequence`)."""
    namespace = {}
    exec((DIR / f"{name}.py").read_text(encoding="utf-8"), namespace)  # noqa: S102
    return namespace["_consequence"](params)


def load(name, answer):
    """The atom's function with `nexus_call` answered by `answer(method, path, kwargs)`,
    which returns a JSON body, or (status, body) for a refusal."""
    calls = []

    async def nexus_call(method, url, **kwargs):
        path = url.removeprefix(API)
        calls.append((method, path, kwargs))
        body = answer(method, path, kwargs)
        if isinstance(body, tuple):
            status, reason = body
            return {"ok": status < 300, "status_code": status, "body": str(reason), "headers": {},
                    "json": reason if isinstance(reason, dict) else None}
        return {"ok": True, "status_code": 200, "json": body, "body": "", "headers": {}}

    namespace = {"nexus_call": nexus_call}
    exec((DIR / f"{name}.py").read_text(encoding="utf-8"), namespace)  # noqa: S102
    return namespace[name], calls


def refused(reason, status=403):
    return (status, {"error": {"code": status, "message": reason}})


def sent_mail(raw: str):
    """The message a call handed to Gmail, parsed back."""
    return email.message_from_bytes(base64.urlsafe_b64decode(raw))


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def message(mid, sender, text, *, to=ME, cc="", subject="Contract terms", thread="t1",
            labels=("INBOX",), extra=(), html=False, files=()):
    headers = [{"name": "From", "value": sender}, {"name": "To", "value": to},
               {"name": "Subject", "value": subject},
               {"name": "Date", "value": "Mon, 23 Nov 2026 09:00:00 -0500"},
               {"name": "Message-ID", "value": f"<{mid}@mail>"}, *extra]
    if cc:
        headers.append({"name": "Cc", "value": cc})
    kind = "text/html" if html else "text/plain"
    parts = [{"mimeType": kind, "body": {"data": b64(text)}}]
    parts += [{"mimeType": "application/pdf", "filename": f, "body": {"attachmentId": "a"}}
              for f in files]
    return {"id": mid, "threadId": thread, "labelIds": list(labels),
            "payload": {"mimeType": "multipart/mixed", "headers": headers, "parts": parts}}


def draft(did, to, subject, text, *, cc="", bcc="", reply=False, thread="t9"):
    headers = [{"name": "To", "value": to}, {"name": "Subject", "value": subject}]
    for name, value in (("Cc", cc), ("Bcc", bcc)):
        if value:
            headers.append({"name": name, "value": value})
    if reply:
        headers.append({"name": "In-Reply-To", "value": "<m1@mail>"})
    return {"id": did, "message": {"id": f"msg-{did}", "threadId": thread, "payload": {
        "mimeType": "text/plain", "headers": headers, "body": {"data": b64(text)}}}}

EFFECTS = {
    "gmail_list_headers": "read",
    "gmail_read_thread": "read",
    "gmail_list_drafts": "read",
    "gmail_list_labels": "read",
    "gmail_find_correspondents": "read",
}


def test_each_atom_passes_the_contract_with_the_effect_it_should_have():
    for name, effect in EFFECTS.items():
        policy = atom(name).policy
        assert policy.effect == effect, name
        if effect != "read":
            assert policy.idempotency_fields and policy.consequence, name


def test_the_helpers_the_mail_atoms_share_are_the_same_in_each():
    """An atom is one file, so a helper several of them need is written in each: the
    copies must not drift apart."""
    import ast

    def helper(path, name):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return next((ast.dump(n) for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == name), None)

    for name in ("_reason", "_addresses", "_bad", "_mime", "_text", "_draft", "_shown",
                 "_named"):
        copies = {helper(p, name) for p in DIR.glob("gmail_*.py")} - {None}
        assert len(copies) <= 1, name


@pytest.mark.asyncio
async def test_drafts_are_listed_with_what_the_send_needs():
    def answer(method, path, kwargs):
        if path == "drafts":
            return {"drafts": [{"id": "d7"}, {"id": "d8"}]}
        return draft(path.split("/")[-1], "c@x.com", "Re: Contract", "Line one.\nLine two. " * 40,
                     reply=True)
    tool, calls = load("gmail_list_drafts", answer)
    out = await tool(query="to:c@x.com", max_results=99)
    assert calls[0][2]["params"] == {"maxResults": 20, "q": "to:c@x.com"}
    first = out["data"]["drafts"][0]
    assert first["draft_id"] == "d7" and first["to"] == ["c@x.com"] and first["is_reply"]
    assert first["opening"].startswith("Line one. Line two.") and len(first["opening"]) == 300
    assert first["length"] > 300 and "text" not in first


@pytest.mark.asyncio
async def test_a_conversation_is_read_oldest_first_without_the_quoting():
    quoted = ("Works for me.\n\nOn Mon, 23 Nov 2026 at 09:00, Dana <c@x.com> wrote:\n"
              "> Can you confirm Thursday?\n> Thanks")
    thread = {"messages": [
        message("m1", "Dana <c@x.com>", "Can you confirm Thursday?\nThanks", cc="ann@x.com"),
        message("m2", ME, quoted, to="c@x.com", labels=("SENT",)),
        message("m3", "Dana <c@x.com>", "> Works for me.\nGreat, see you then.",
                labels=("INBOX", "UNREAD"), files=["agenda.pdf"]),
    ]}
    tool, calls = load("gmail_read_thread", lambda *a: thread)
    out = await tool(thread_id="t1")
    assert calls[0][1] == "threads/t1" and calls[0][2]["params"] == {"format": "full"}
    data = out["data"]
    assert data["count"] == 3 and data["subject"] == "Contract terms"
    assert [m["id"] for m in data["messages"]] == ["m1", "m2", "m3"]
    assert data["messages"][0]["cc"] == ["ann@x.com"]
    assert data["messages"][1]["text"] == "Works for me."
    assert data["messages"][2]["text"] == "Great, see you then."
    assert data["messages"][2]["labels"] == ["INBOX", "UNREAD"]
    assert data["messages"][2]["attachments"] == ["agenda.pdf"]


@pytest.mark.asyncio
async def test_a_long_conversation_fits_and_the_newest_message_is_the_one_kept_whole():
    thread = {"messages": [
        message(f"m{i}", "Dana <c@x.com>", f"Message {i}. " + "word " * 1500)
        for i in range(12)
    ] + [message("m12", "Dana <c@x.com>", "The answer is yes. " * 20)]}
    tool, _ = load("gmail_read_thread", lambda *a: thread)
    out = await tool(thread_id="t1")
    messages = out["data"]["messages"]
    assert len(json.dumps(out)) < 10_000  # shown twice by the sandbox: still under 20,000
    assert "cut" not in messages[-1] and messages[-1]["text"].startswith("The answer is yes.")
    assert messages[0]["cut"] and messages[0]["length"] > 7000
    assert messages[0]["text"].startswith("Message 0.")  # every message keeps its beginning
    assert not (await tool(thread_id=""))["success"]
    endless = {"messages": [message(f"m{i}", "Dana <c@x.com>", "word " * 900)
                            for i in range(60)]}
    tool, _ = load("gmail_read_thread", lambda *a: endless)
    out = await tool(thread_id="t1")
    assert len(json.dumps(out)) < 10_000 and out["data"]["count"] == 60
    assert out["data"]["earlier_messages_not_shown"] == 40
    assert out["data"]["messages"][-1]["id"] == "m59"


@pytest.mark.asyncio
async def test_the_header_list_pages_and_says_googles_reason():
    def answer(method, path, kwargs):
        if path == "messages":
            return {"messages": [{"id": "m1"}], "nextPageToken": "p2", "resultSizeEstimate": 90}
        return message("m1", "Pat <pat@x.com>", "x", cc="ann@x.com")
    tool, calls = load("gmail_list_headers", answer)
    out = await tool(query="from:pat", page_token="p1")
    assert calls[0][2]["params"] == {"maxResults": 20, "q": "from:pat", "pageToken": "p1"}
    assert out["data"]["next_page_token"] == "p2"
    assert out["data"]["messages"][0]["thread_id"] == "t1"
    assert out["data"]["messages"][0]["cc"] == "ann@x.com"
    tool, _ = load("gmail_list_headers", lambda *a: refused("Invalid query", 400))
    assert "400 Invalid query" in (await tool(query="((("))["error"]


@pytest.mark.asyncio
async def test_the_persons_own_labels_are_read_by_name_not_by_gmails_id():
    """Live, 2026-11-24: a labelled test thread came back as "Label_12"."""
    labelled = message("m1", "Pat <pat@x.com>", "x", labels=("INBOX", "Label_12"))

    def answer(method, path, kwargs):
        if path == "labels":
            return {"labels": [{"id": "Label_12", "name": "Deals"},
                               {"id": "INBOX", "name": "INBOX"}]}
        if path == "messages":
            return {"messages": [{"id": "m1"}]}
        return {"messages": [labelled]} if path.startswith("threads/") else labelled

    tool, calls = load("gmail_list_headers", answer)
    assert (await tool())["data"]["messages"][0]["labels"] == ["INBOX", "Deals"]
    tool, calls = load("gmail_read_thread", answer)
    assert (await tool(thread_id="t1"))["data"]["messages"][0]["labels"] == ["INBOX", "Deals"]
    # no label of theirs, no extra read
    plain = message("m1", "Pat <pat@x.com>", "x")
    tool, calls = load("gmail_read_thread", lambda *a: {"messages": [plain]})
    await tool(thread_id="t1")
    assert [c[1] for c in calls] == ["threads/t1"]


@pytest.mark.asyncio
async def test_a_name_is_resolved_from_the_persons_own_mail():
    mail = {
        "m1": message("m1", "Sam Rivera <sam@rivera.co>", "x", to=ME),
        "m2": message("m2", ME, "x", to="Sam Rivera <sam@rivera.co>, kim@x.com"),
        "m3": message("m3", "Samuel Hart <shart@hartfield.com>", "x", to=ME,
                      cc="sam@rivera.co"),
        "m4": message("m4", "Sam Rivera (via Docs) <comments-noreply@docs.example.com>",
                      "x", to=f"{ME}, team@flotsam.org"),
        "m5": message("m5", "Sam Rivera (via Docs) <comments-noreply@docs.example.com>",
                      "x", to=ME),
        "m6": message("m6", "Sam Rivera (via Docs) <comments-noreply@docs.example.com>",
                      "x", to=ME),
        "m7": message("m7", "Sam Rivera (via Docs) <comments-noreply@docs.example.com>",
                      "x", to=ME),
    }

    def answer(method, path, kwargs):
        if path == "messages":
            return {"messages": [{"id": k} for k in mail]}
        if path == "profile":
            return {"emailAddress": ME}
        return mail[path.split("/")[-1]]

    tool, calls = load("gmail_find_correspondents", answer)
    out = await tool(name="Sam")
    assert calls[0][2]["params"]["q"] == "from:(sam) OR to:(sam) OR cc:(sam)"
    people = out["data"]["people"]
    # a person before a notification address, however much it sent; flotsam.org is no Sam
    assert [(p["email"], p["messages"]) for p in people] == [
        ("sam@rivera.co", 3), ("shart@hartfield.com", 1),
        ("comments-noreply@docs.example.com", 4)]
    assert people[2]["automated"] and "automated" not in people[0]
    assert people[0]["name"] == "Sam Rivera"
    assert ME not in [p["email"] for p in people]
    one = await tool(name="sam rivera")
    assert [p["email"] for p in one["data"]["people"]] == [
        "sam@rivera.co", "comments-noreply@docs.example.com"]
    none = await tool(name="zed")
    assert none["success"] and none["data"]["people"] == [] and "No one" in none["data"]["note"]
    assert not (await tool(name=" "))["success"]
