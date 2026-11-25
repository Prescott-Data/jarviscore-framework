"""The Gmail atoms that write: drafts (new, reply, forward), sending a message or a
draft, tidying and trashing conversations, and labels. The request each sends, the
result it shapes, what it refuses, and what it says a call does."""

import base64
import email

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
    "gmail_create_draft": "write",
    "gmail_draft_reply": "write",
    "gmail_draft_forward": "write",
    "gmail_triage_threads": "write",
    "gmail_create_label": "write",
    "gmail_send_email": "notify",
    "gmail_send_draft": "notify",
    "gmail_trash_threads": "destructive",
    "gmail_delete_label": "destructive",
}


def test_each_atom_passes_the_contract_with_the_effect_it_should_have():
    for name, effect in EFFECTS.items():
        policy = atom(name).policy
        assert policy.effect == effect, name
        if effect != "read":
            assert policy.idempotency_fields and policy.consequence, name


def test_a_draft_and_tidying_run_on_their_own_and_what_sends_or_deletes_waits():
    """What each atom declares; an institution's control policy may ask for more."""
    quiet = {"gmail_create_draft", "gmail_draft_reply", "gmail_draft_forward",
             "gmail_triage_threads"}
    for name in EFFECTS:
        assert atom(name).policy.requires_approval is (name not in quiet), name


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
async def test_a_new_draft_carries_cc_bcc_and_a_subject_with_accents():
    tool, calls = load("gmail_create_draft", lambda *a: {"id": "d1", "message": {"id": "m"}})
    out = await tool(to="Sam Rivera <Sam@Example.com>, ann@example.com",
                     subject="Café  contract\nBcc: x@evil.com", body="Hello Sam,\n\nTerms below.",
                     cc="kim@example.com", bcc="files@example.org")
    assert out["success"], out
    method, path, kwargs = calls[0]
    assert (method, path) == ("POST", "drafts")
    mail = sent_mail(kwargs["json"]["message"]["raw"])
    assert mail["To"] == "sam@example.com, ann@example.com" and mail["Cc"] == "kim@example.com"
    assert mail["Bcc"] == "files@example.org"
    # a line break in a subject cannot start a header of its own
    assert str(email.header.make_header(email.header.decode_header(mail["Subject"]))) == \
        "Café contract Bcc: x@evil.com"
    assert mail.get_payload(decode=True).decode().strip() == "Hello Sam,\n\nTerms below."
    assert out["data"] == {"draft_id": "d1", "thread_id": None,
                           "to": ["sam@example.com", "ann@example.com"],
                           "cc": ["kim@example.com"], "bcc": ["files@example.org"],
                           "subject": "Café contract Bcc: x@evil.com"}
    for bad in ({"to": "", "subject": "s", "body": "b"}, {"to": ME, "subject": "", "body": "b"},
                {"to": ME, "subject": "s", "body": " "}, {"to": "Sam", "subject": "s",
                                                           "body": "b"}):
        assert not (await tool(**bad))["success"]
    assert len(calls) == 1
    tool, _ = load("gmail_create_draft", lambda *a: refused("Insufficient Permission"))
    out = await tool(to=ME, subject="s", body="b")
    assert "403 Insufficient Permission" in out["error"]


def replying(original):
    def answer(method, path, kwargs):
        if path == "profile":
            return {"emailAddress": ME}
        if method == "GET":
            return original
        return {"id": "d7"}
    return answer


@pytest.mark.asyncio
async def test_a_reply_is_drafted_in_its_thread_to_the_sender_and_never_sent():
    original = message("m1", "Dana <c@x.com>", "Can you confirm?",
                       to=f"{ME}, Ann <ann@x.com>", cc="kim@x.com", subject="Action items")
    tool, calls = load("gmail_draft_reply", replying(original))
    out = await tool(message_id="m1", body="By Friday.")
    assert out["data"] == {"draft_id": "d7", "thread_id": "t1", "to": ["c@x.com"], "cc": [],
                           "bcc": [], "subject": "Re: Action items"}
    assert [c[1] for c in calls] == ["messages/m1", "profile", "drafts"]  # nothing is sent
    sent = calls[-1][2]["json"]["message"]
    assert sent["threadId"] == "t1"
    mail = sent_mail(sent["raw"])
    assert mail["To"] == "c@x.com" and mail["Cc"] is None
    assert mail["In-Reply-To"] == "<m1@mail>" and mail["References"] == "<m1@mail>"
    assert mail["Subject"] == "Re: Action items"


@pytest.mark.asyncio
async def test_reply_all_keeps_everyone_on_the_message_but_the_person():
    original = message(
        "m1", "Dana <c@x.com>", "Can you confirm?", to=f"{ME}, Ann <ann@x.com>",
        cc="kim@x.com, C@x.com", subject="Re: Action items",
        extra=[{"name": "Reply-To", "value": "desk@x.com"},
               {"name": "References", "value": "<m0@mail>"}])
    tool, calls = load("gmail_draft_reply", replying(original))
    out = await tool(message_id="m1", body="By Friday.", reply_all=True, cc="pa@example.org",
                     bcc="files@example.org")
    data = out["data"]
    assert data["to"] == ["desk@x.com"]  # the Reply-To, when the message has one
    assert data["cc"] == ["ann@x.com", "kim@x.com", "c@x.com", "pa@example.org"]
    assert data["bcc"] == ["files@example.org"] and data["subject"] == "Re: Action items"
    mail = sent_mail(calls[-1][2]["json"]["message"]["raw"])
    assert ME not in mail["Cc"] and mail["References"] == "<m0@mail> <m1@mail>"
    tool, _ = load("gmail_draft_reply", lambda *a: refused("Requested entity was not found.",
                                                           404))
    out = await tool(message_id="nope", body="x")
    assert "404 Requested entity was not found." in out["error"]


@pytest.mark.asyncio
async def test_a_reply_to_the_persons_own_message_follows_up_with_its_recipients():
    """Live, 2026-11-24: a reply to a message he had sent was addressed to himself. A mail
    client sends such a reply on to the people the message went to."""
    sent = message("m1", f"Alex <{ME}>", "Any news?", to="Sam <sam@x.com>, ann@x.com",
                   cc=f"kim@x.com, {ME}", subject="Contract", labels=("SENT",))
    tool, _ = load("gmail_draft_reply", replying(sent))
    out = await tool(message_id="m1", body="Following up.")
    assert out["data"]["to"] == ["sam@x.com", "ann@x.com"] and out["data"]["cc"] == []
    out = await tool(message_id="m1", body="Following up.", reply_all=True)
    assert out["data"]["to"] == ["sam@x.com", "ann@x.com"] and out["data"]["cc"] == ["kim@x.com"]
    # a note to himself is answered to himself: there is nobody else on it
    note = message("m2", f"Alex <{ME}>", "Remember.", to=ME, labels=("SENT", "INBOX"))
    tool, _ = load("gmail_draft_reply", replying(note))
    assert (await tool(message_id="m2", body="Done."))["data"]["to"] == [ME]


@pytest.mark.asyncio
async def test_a_forward_carries_the_text_and_says_which_attachments_it_left_out():
    original = message("m1", "Dana <c@x.com>", "<p>Terms attached.</p><p>Thanks</p>",
                       subject="Contract", html=True, files=["scan.pdf"])
    tool, calls = load("gmail_draft_forward",
                       lambda m, p, k: original if m == "GET" else {"id": "d8"})
    out = await tool(message_id="m1", to="sam@example.com", note="For your review.",
                     cc="kim@example.com")
    assert out["success"], out
    assert calls[0][2]["params"] == {"format": "full"}
    mail = sent_mail(calls[-1][2]["json"]["message"]["raw"])
    text = mail.get_payload(decode=True).decode()
    assert mail["Subject"] == "Fwd: Contract" and mail["To"] == "sam@example.com"
    assert text.startswith("For your review.\n\n---------- Forwarded message ---------\n"
                           "From: Dana <c@x.com>\n")
    assert "Terms attached.\nThanks" in text and "<p>" not in text
    assert out["data"]["attachments_left_out"] == ["scan.pdf"]
    assert "scan.pdf" in out["data"]["note"]
    assert "threadId" not in calls[-1][2]["json"]["message"]
    assert not (await tool(message_id="m1", to=""))["success"]


@pytest.mark.asyncio
async def test_a_new_message_is_sent_as_typed_and_says_who_gets_it_first():
    tool, calls = load("gmail_send_email", lambda *a: {"id": "m9", "threadId": "t9"})
    params = {"to": "sam@example.com", "subject": "Thursday", "cc": "ann@example.com",
              "body": "Sam,\n\nThursday at 11 works. " + "More detail. " * 200}
    out = await tool(**params)
    assert out["data"]["sent"] and out["data"]["message_id"] == "m9"
    method, path, kwargs = calls[0]
    assert (method, path) == ("POST", "messages/send")
    mail = sent_mail(kwargs["json"]["raw"])
    assert mail.get_payload(decode=True).decode().strip() == params["body"].strip()

    words = consequence("gmail_send_email", params)
    assert words.startswith(
        "Sends an email in the person's name to: sam@example.com; cc: ann@example.com. "
        'Subject: "Thursday". It reads: "Sam, Thursday at 11 works. More detail.')
    assert "characters in all" in words and len(words) < 900
    many = consequence("gmail_send_email", {
        "to": ", ".join(f"p{i}@example.com" for i in range(40)), "subject": "s", "body": "b"})
    assert "p7@example.com and 32 more" in many
    assert not (await tool(to="sam", subject="s", body="b"))["success"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_message_may_be_sent_as_html_and_no_other_kind():
    tool, calls = load("gmail_send_email", lambda *a: {"id": "m9", "threadId": "t9"})
    out = await tool(to="sam@example.com", subject="Thursday", body="<p>At <b>11</b>.</p>",
                     body_type="text/html")
    assert out["success"]
    mail = sent_mail(calls[0][2]["json"]["raw"])
    assert mail.get_content_type() == "text/html"
    assert mail.get_payload(decode=True).decode().strip() == "<p>At <b>11</b>.</p>"
    plain = await tool(to="sam@example.com", subject="Thursday", body="At 11.")
    assert plain["success"]
    assert sent_mail(calls[1][2]["json"]["raw"]).get_content_type() == "text/plain"
    refused_kind = await tool(to="sam@example.com", subject="s", body="b",
                              body_type="application/pdf")
    assert not refused_kind["success"] and "text/html" in refused_kind["error"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_draft_is_sent_as_it_stands_once_the_call_describes_that_very_draft():
    body = "Dana,\n\nBy Friday. I will send the signed copy then.\n\nAlex"
    held = draft("d7", "c@x.com", "Re: Action items", body, cc="ann@x.com", reply=True,
                 thread="t1")

    def answer(method, path, kwargs):
        if method == "GET":
            return held
        return {"id": "m10", "threadId": "t1"}

    tool, calls = load("gmail_send_draft", answer)
    ok = {"draft_id": "d7", "to": "C@x.com", "cc": "ann@x.com", "subject": "re: action items",
          "opening": "Dana, By Friday. I will send the signed copy then."}
    out = await tool(**ok)
    assert out["success"], out
    method, path, kwargs = calls[-1]
    assert (method, path) == ("POST", "drafts/send") and kwargs["json"] == {"id": "d7"}
    assert out["data"] == {"sent": True, "message_id": "m10", "thread_id": "t1",
                           "to": ["c@x.com"], "cc": ["ann@x.com"], "bcc": [],
                           "subject": "Re: Action items", "in_conversation": True}
    # anything that is not the draft's own stops the send, and the answer says what differs
    for wrong, said in (
        ({"to": "c@x.com, eve@x.com"}, "to is c@x.com in the draft"),
        ({"cc": ""}, "cc is ann@x.com in the draft"),
        ({"bcc": "eve@x.com"}, "bcc is empty in the draft"),
        ({"subject": "Action items"}, "the draft's subject is 'Re: Action items'"),
        ({"opening": "Dana, by Monday. I will send the signed copy then."},
         "the draft begins"),
        ({"opening": "Dana,"}, "the draft begins"),  # too little to know it by
    ):
        refusal = await tool(**{**ok, **wrong})
        assert not refusal["success"] and said in refusal["error"], refusal
        assert refusal["error"].startswith("nothing was sent")
    assert [c[1] for c in calls].count("drafts/send") == 1


@pytest.mark.asyncio
async def test_a_short_draft_is_known_by_all_of_it_and_googles_refusal_is_passed_on():
    held = draft("d1", "c@x.com", "Hi", "Yes.")
    tool, calls = load("gmail_send_draft",
                       lambda m, p, k: held if m == "GET" else refused("Daily limit", 429))
    out = await tool(draft_id="d1", to="c@x.com", subject="Hi", opening="Yes.")
    assert not out["success"] and "429 Daily limit" in out["error"]
    nobody = draft("d2", "", "Hi", "Yes.")
    tool, calls = load("gmail_send_draft", lambda m, p, k: nobody)
    out = await tool(draft_id="d2", to="", subject="Hi", opening="Yes.")
    assert "nobody in To" in out["error"] and len(calls) == 1


def test_sending_a_draft_says_recipients_then_subject_then_how_it_begins():
    words = consequence("gmail_send_draft", {
        "draft_id": "d7", "to": "c@x.com", "cc": "ann@x.com", "subject": "Re: Action items",
        "opening": "Dana, By Friday."})
    assert words == (
        "Sends the draft, in the person's name, to: c@x.com; cc: ann@x.com. Subject: "
        '"Re: Action items". It begins: "Dana, By Friday." The whole draft is sent as it '
        "stands in Gmail. A sent email cannot be recalled.")
    # a consequence is cut at 1,500 characters: the longest one still fits
    longest = consequence("gmail_send_draft", {
        "to": ", ".join(f"person{i}@example.com" for i in range(60)),
        "cc": ", ".join(f"copy{i}@example.com" for i in range(60)),
        "bcc": ", ".join(f"blind{i}@example.com" for i in range(60)),
        "subject": "s" * 400, "opening": "o" * 5000})
    assert len(longest) < 1500


def modifying(fail=()):
    def answer(method, path, kwargs):
        if path == "labels":
            return {"labels": [{"id": "Label_7", "name": "Deals"}]}
        thread = path.split("/")[1]
        return refused("Not Found", 404) if thread in fail else {"id": thread}
    return answer


@pytest.mark.asyncio
async def test_many_conversations_are_tidied_in_one_call_on_the_thread():
    tool, calls = load("gmail_triage_threads", modifying())
    out = await tool(thread_ids=["t1", "t2", "t1", "t3"], archive=True, mark="read",
                     star="star", add_labels="deals")
    assert out["data"] == {"changed": 3, "failed": [],
                           "did": ["archived", "marked read", "starred", "labelled deals"]}
    posts = [c for c in calls if c[0] == "POST"]
    assert [c[1] for c in posts] == [f"threads/{t}/modify" for t in ("t1", "t2", "t3")]
    assert posts[0][2]["json"] == {"addLabelIds": ["STARRED", "Label_7"],
                                   "removeLabelIds": ["INBOX", "UNREAD"]}
    # system labels need no lookup
    tool, calls = load("gmail_triage_threads", modifying())
    await tool(thread_ids=["t1"], mark="unread", star="unstar")
    assert [c[1] for c in calls] == ["threads/t1/modify"]
    assert calls[0][2]["json"] == {"addLabelIds": ["UNREAD"], "removeLabelIds": ["STARRED"]}


@pytest.mark.asyncio
async def test_tidying_reports_what_gmail_refused_and_refuses_what_it_cannot_do():
    tool, _ = load("gmail_triage_threads", modifying(fail={"t2"}))
    out = await tool(thread_ids=["t1", "t2"], archive=True)
    assert out["success"] and out["data"]["changed"] == 1
    assert out["data"]["failed"] == [{"thread_id": "t2", "error": "404 Not Found"}]
    for bad, said in (
        ({"thread_ids": []}, "at least one"),
        ({"thread_ids": ["t1"]}, "nothing to do"),
        ({"thread_ids": ["t1"], "mark": "seen"}, '"read" or "unread"'),
        ({"thread_ids": ["t1"], "add_labels": "Waiting on"}, "gmail_create_label"),
        ({"thread_ids": ["t1"], "add_labels": "Deals", "remove_labels": "deals"}, "both"),
        ({"thread_ids": [f"t{i}" for i in range(51)], "archive": True}, "at most 50"),
    ):
        refusal = await tool(**bad)
        assert not refusal["success"] and said in refusal["error"], refusal
    tool, _ = load("gmail_triage_threads", modifying(fail={"t1"}))
    assert "404 Not Found" in (await tool(thread_ids=["t1"], archive=True))["error"]


def trashing(subjects):
    def answer(method, path, kwargs):
        thread = path.split("/")[1]
        if method == "GET":
            return {"messages": [message("m", "a@x.com", "x", subject=subjects[thread])]}
        return {"id": thread}
    return answer


@pytest.mark.asyncio
async def test_trashing_checks_each_subject_first():
    tool, calls = load("gmail_trash_threads",
                       trashing({"t1": "Re: Weekly digest", "t2": "Offer ends"}))
    out = await tool(thread_ids=["t1", "t2"], subjects=["weekly digest", "Offer ends"])
    assert out["data"]["trashed"] == 2 and out["data"]["failed"] == []
    assert [(c[0], c[1]) for c in calls][-2:] == [("POST", "threads/t1/trash"),
                                                  ("POST", "threads/t2/trash")]
    source = (DIR / "gmail_trash_threads.py").read_text()
    assert '"DELETE"' not in source
    wrong = await tool(thread_ids=["t1", "t2"], subjects=["Weekly digest", "Board papers"])
    assert not wrong["success"] and "'Offer ends', not 'Board papers'" in wrong["error"]
    assert "nothing was moved" in wrong["error"]
    assert [c[0] for c in calls].count("POST") == 2  # the refused call moved nothing
    for bad in ({"thread_ids": ["t1"], "subjects": []},
                {"thread_ids": ["t1", "t1"], "subjects": ["a", "a"]},
                {"thread_ids": [], "subjects": []}):
        assert not (await tool(**bad))["success"]


def test_trashing_says_the_subjects():
    words = consequence("gmail_trash_threads", {"thread_ids": ["t1", "t2"],
                                                "subjects": ["Weekly digest", "Offer ends"]})
    assert words == (
        'Moves 2 Gmail conversations to the trash: "Weekly digest"; "Offer ends". Gmail '
        "keeps them in Trash for 30 days, where they can be restored, then deletes them for "
        "good.")
    full = consequence("gmail_trash_threads", {"thread_ids": [f"t{i}" for i in range(25)],
                                               "subjects": ["s" * 200] * 25})
    assert "and 13 more" in full and len(full) < 1500


@pytest.mark.parametrize("params", [
    {"add_labels": "spam"}, {"add_labels": "Receipts, TRASH"}, {"remove_labels": "sent"},
    {"add_labels": "Draft"},
])
async def test_the_tidying_tool_that_asks_nobody_cannot_spam_trash_or_relabel_what_a_message_is(
    params,
):
    """It runs without approval because everything it does is undoable and reaches nobody.
    Spam and Trash are neither; they are refused before any request is made."""
    tool, calls = load("gmail_triage_threads", modifying())
    result = await tool(thread_ids=["t1"], **params)
    assert result["success"] is False and "only tidies" in result["error"]
    assert calls == []
