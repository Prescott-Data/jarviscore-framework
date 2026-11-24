"""The Drive atoms: finding a file in plain terms, shared drives included, reading one as
text a page at a time, and sharing one by its name and id."""

import pytest

from jarviscore.execution.atom_contract import SHIPPED_ATOMS_DIR, read_contract

SYSTEM = "google_drive"
DIR = SHIPPED_ATOMS_DIR / SYSTEM
API = "https://www.googleapis.com/drive/v3/files"
DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"


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
        if isinstance(body, str):  # a file's text, read from the answer's body
            return {"ok": True, "status_code": 200, "json": None, "body": body, "headers": {},
                    "content": {"__bytes__": "never-read"}}
        return {"ok": True, "status_code": 200, "json": body, "body": "", "headers": {}}

    namespace = {"nexus_call": nexus_call}
    exec((DIR / f"{name}.py").read_text(encoding="utf-8"), namespace)  # noqa: S102
    return namespace[name], calls


@pytest.mark.asyncio
async def test_sharing_names_the_file_and_the_recipient_and_checks_the_file_first():
    result = contract("google_drive_share_file")
    assert result.ok, result.report()
    assert result.atom.policy.effect == "notify" and result.atom.policy.requires_approval
    assert consequence("google_drive_share_file", {
        "file_id": "f1", "name": "Board notes", "role": "writer",
        "email": "Sam@Example.com", "message": "For Thursday."}) == (
        'Lets sam@example.com edit the Drive file "Board notes". Google emails them the link '
        'with this note: "For Thursday.". They keep that access until it is removed in Drive.')

    def answer(method, path, kwargs):
        if method == "GET":
            return {"id": "f1", "name": "Board notes", "webViewLink": "https://d/f1"}
        return {"id": "p1", "role": "reader", "emailAddress": "sam@example.com"}

    tool, calls = load("google_drive_share_file", answer)
    out = await tool(file_id="f1", name="board  NOTES", email="Sam@Example.com")
    assert out["data"] == {"shared_with": "sam@example.com", "role": "reader",
                           "name": "Board notes", "link": "https://d/f1", "emailed": True}
    method, path, kwargs = calls[-1]
    assert (method, path) == ("POST", "/f1/permissions")
    assert kwargs["json"] == {"type": "user", "role": "reader", "emailAddress": "sam@example.com"}
    assert kwargs["params"]["sendNotificationEmail"] == "true"
    for bad, said in (({"name": "Other file"}, "nobody was given access"),
                      ({"email": "sam, ann@x.com"}, "one address"),
                      ({"role": "owner"}, '"reader", "commenter" or "writer"')):
        refusal = await tool(**{"file_id": "f1", "name": "Board notes",
                                "email": "sam@example.com", **bad})
        assert not refusal["success"] and said in refusal["error"], refusal
    assert [c[0] for c in calls].count("POST") == 1
    tool, _ = load("google_drive_share_file", lambda m, p, k: (
        {"id": "f1", "name": "Board notes"} if m == "GET"
        else (403, {"error": {"message": "The user does not have sufficient permissions."}})))
    out = await tool(file_id="f1", name="Board notes", email="sam@example.com")
    assert "does not have sufficient permissions" in out["error"]
    assert "only a file this application created" in out["error"]


def test_finding_and_reading_are_reads_that_pass_the_contract():
    for name in ("google_drive_search_files", "google_drive_read_file"):
        assert atom(name).policy.effect == "read"
        assert '"POST"' not in (DIR / f"{name}.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_file_is_found_by_plain_terms_in_shared_drives_too():
    tool, calls = load("google_drive_search_files", lambda *a: {
        "nextPageToken": "p2",
        "files": [{"id": "f1", "name": "Board pack Q4", "mimeType": DOC, "driveId": "d1",
                   "modifiedTime": "2026-11-20T10:00:00Z", "webViewLink": "https://docs/f1",
                   "owners": [{"emailAddress": "lee@example.com"}]},
                  {"id": "f2", "name": "scan.pdf", "mimeType": "application/pdf"}]})
    out = await tool(name="Lee's board pack", kind="doc")
    params = calls[0][2]["params"]
    assert params["q"] == ("name contains 'Lee\\'s board pack' and "
                           f"mimeType = '{DOC}' and trashed = false")
    assert params["supportsAllDrives"] == "true" and params["corpora"] == "allDrives"
    assert params["includeItemsFromAllDrives"] == "true"
    assert params["orderBy"] == "modifiedTime desc"
    assert calls[0][2]["provider"] == "google_drive"
    first, second = out["data"]["files"]
    assert first == {"id": "f1", "name": "Board pack Q4", "kind": "doc",
                     "modified": "2026-11-20T10:00:00Z", "owner": "lee@example.com",
                     "link": "https://docs/f1", "shared_drive": True}
    assert second["kind"] == "pdf" and "shared_drive" not in second
    assert out["data"]["next_page_token"] == "p2"


@pytest.mark.asyncio
async def test_a_text_search_is_not_sorted_and_a_raw_query_is_used_as_it_is():
    tool, calls = load("google_drive_search_files", lambda *a: {"files": []})
    out = await tool(text="indemnity", page_token="p2", page_size=500)
    params = calls[0][2]["params"]
    assert params["q"] == "fullText contains 'indemnity' and trashed = false"
    assert "orderBy" not in params  # Drive refuses a sort with a text search
    assert params["pageToken"] == "p2" and params["pageSize"] == 50
    assert out["data"]["files"] == [] and "No file matches" in out["data"]["note"]
    await tool(query="'me' in owners and trashed = true", kind="sheet")
    assert calls[1][2]["params"]["q"] == (
        f"mimeType = '{SHEET}' and ('me' in owners and trashed = true)")
    assert not (await tool())["success"]
    assert not (await tool(name="x", kind="spreadsheet"))["success"]
    assert len(calls) == 2
    tool, _ = load("google_drive_search_files",
                   lambda *a: (400, {"error": {"message": "Invalid Value"}}))
    assert "400 Invalid Value" in (await tool(query="((("))["error"]


def reading(kind, text, name="Notes", size=None):
    def answer(method, path, kwargs):
        if path == "/f1" and "alt" not in kwargs["params"]:
            return {"id": "f1", "name": name, "mimeType": kind, "webViewLink": "https://d/f1",
                    **({"size": size} if size else {})}
        return text
    return answer


@pytest.mark.asyncio
async def test_a_long_document_is_read_a_page_at_a_time_from_the_text_not_the_bytes():
    whole = "".join(f"Line {i}.\r\n" for i in range(3000))
    tool, calls = load("google_drive_read_file", reading(DOC, whole))
    out = await tool(file_id="f1")
    assert calls[1][1] == "/f1/export" and calls[1][2]["params"] == {"mimeType": "text/plain"}
    data = out["data"]
    assert len(data["text"]) == 8500 and data["text"].startswith("Line 0.\nLine 1.")
    assert data["length"] == len(whole.replace("\r\n", "\n")) and data["next_offset"] == 8500
    nxt = await tool(file_id="f1", offset=data["next_offset"], max_chars=50_000)
    assert nxt["data"]["offset"] == 8500 and len(nxt["data"]["text"]) == 8500
    assert data["text"] + nxt["data"]["text"] == whole.replace("\r\n", "\n")[:17000]
    last = await tool(file_id="f1", offset=data["length"] - 100)
    assert "next_offset" not in last["data"] and len(last["data"]["text"]) == 100


@pytest.mark.asyncio
async def test_each_kind_of_file_is_read_the_way_it_can_be_or_refused_plainly():
    tool, calls = load("google_drive_read_file", reading(SHEET, "a,b\n1,2\n"))
    out = await tool(file_id="f1")
    assert calls[1][2]["params"] == {"mimeType": "text/csv"}
    assert out["data"]["text"] == "a,b\n1,2\n" and "first tab" in out["data"]["sheet_note"]
    tool, calls = load("google_drive_read_file", reading("text/markdown", "﻿# Notes\n"))
    out = await tool(file_id="f1")
    assert calls[1][1] == "/f1" and calls[1][2]["params"]["alt"] == "media"
    assert out["data"]["text"] == "# Notes\n"
    tool, calls = load("google_drive_read_file", reading("application/pdf", "", name="scan.pdf"))
    out = await tool(file_id="f1")
    assert not out["success"] and len(calls) == 1
    assert "'scan.pdf' is a application/pdf, which cannot be read as text here" in out["error"]
    assert "https://d/f1" in out["error"]
    tool, _ = load("google_drive_read_file", reading("text/plain", "x", size="20000000"))
    assert "too large" in (await tool(file_id="f1"))["error"]
    tool, _ = load("google_drive_read_file",
                   lambda *a: (404, {"error": {"message": "File not found: f9."}}))
    assert "404 File not found: f9." in (await tool(file_id="f9"))["error"]
    assert not (await tool(file_id=" "))["success"]
