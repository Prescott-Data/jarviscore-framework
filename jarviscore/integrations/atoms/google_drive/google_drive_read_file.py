ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

# google_drive_export_file returns a whole export however long and needs the caller to
# know which format a file can be exported as. This one looks at what the file is, reads
# it as text the right way, and gives it a page at a time.

_API = "https://www.googleapis.com/drive/v3/files"
_GOOGLE = "application/vnd.google-apps."
# what each Google file is read as
_EXPORTS = {
    _GOOGLE + "document": "text/plain",
    _GOOGLE + "presentation": "text/plain",
    _GOOGLE + "spreadsheet": "text/csv",
}
_TEXT = ("text/", "application/json", "application/xml", "application/x-yaml")
# A page is sized to be read whole by a model.
_PAGE = 8500
_LARGEST = 10_000_000  # bytes of a plain file read here (Google's own limit for an export)


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


async def google_drive_read_file(file_id: str, offset: int = 0, max_chars: int = 8500) -> dict:
    """Read a Drive file as text, a page at a time.

    `file_id` is the file's `id` from google_drive_search_files. A Google Doc and a Slides
    file are read as their plain text; a Google Sheet as the CSV of its FIRST tab only
    (for other tabs, a range, or the links in cells, use the google_sheets tools); a text
    file (txt, csv, markdown, json) as it is. A PDF, a Word or Excel file, an image or
    any other file cannot be read here: the answer says so, and that is not a failure of
    the file.

    Returns `text` (at most `max_chars`, 8500 at most), `length` (of the whole file),
    `offset`, and `next_offset` when there is more: call again with it as `offset` for the
    next page. Also `name`, `kind` and `link`. For a Google Doc with tabs, or one that
    is long, google_drive_get_document reads it a tab at a time.
    https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
    """
    file_id = str(file_id or "").strip()
    if not file_id:
        return {"success": False, "data": None, "error": "a file id is needed"}
    start = max(0, int(offset or 0))
    page = max(500, min(int(max_chars or _PAGE), _PAGE))
    about = await nexus_call(  # noqa: F821
        "GET",
        f"{_API}/{file_id}",
        provider="google_drive",
        params={"fields": "id,name,mimeType,size,webViewLink", "supportsAllDrives": "true"},
    )
    if not about["ok"]:
        return {"success": False, "data": None,
                "error": f"the file could not be found: {_reason(about)}"}
    file = about["json"] or {}
    kind = str(file.get("mimeType") or "")
    if kind in _EXPORTS:
        got = await nexus_call(  # noqa: F821
            "GET",
            f"{_API}/{file_id}/export",
            provider="google_drive",
            params={"mimeType": _EXPORTS[kind]},
        )
    elif kind.startswith(_TEXT):
        if int(file.get("size") or 0) > _LARGEST:
            return {"success": False, "data": None,
                    "error": f"{file.get('name')!r} is too large to read here "
                             f"({file.get('size')} bytes)"}
        got = await nexus_call(  # noqa: F821
            "GET",
            f"{_API}/{file_id}",
            provider="google_drive",
            params={"alt": "media", "supportsAllDrives": "true"},
        )
    else:
        what = "a folder" if kind == _GOOGLE + "folder" else f"a {kind or 'file of unknown type'}"
        return {"success": False, "data": None,
                "error": f"{file.get('name')!r} is {what}, which cannot be read as text here. "
                         "Google Docs, Sheets, Slides and plain text files can. Its link: "
                         f"{file.get('webViewLink')}"}
    if not got["ok"]:
        return {"success": False, "data": None,
                "error": f"{file.get('name')!r} could not be read: {_reason(got)}"}
    whole = str(got.get("body") or "").replace("\r\n", "\n").lstrip("﻿")
    text = whole[start:start + page]
    out = {
        "name": file.get("name"),
        "kind": kind,
        "link": file.get("webViewLink"),
        "text": text,
        "offset": start,
        "length": len(whole),
    }
    if start + page < len(whole):
        out["next_offset"] = start + page
        out["note"] = (f"This is characters {start} to {start + len(text)} of {len(whole)}: "
                       "call again with offset set to next_offset for more.")
    if kind == _GOOGLE + "spreadsheet":
        out["sheet_note"] = ("Only the first tab, as CSV. Other tabs and ranges: "
                             "google_sheets_get_spreadsheet and google_sheets_read_range.")
    if not whole.strip():
        out["note"] = "The file has no text."
    return {"success": True, "data": out, "error": None}
