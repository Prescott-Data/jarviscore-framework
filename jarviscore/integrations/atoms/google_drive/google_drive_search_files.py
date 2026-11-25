ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

# Asked in plain terms (a name, words in the text, a kind of file), this writes Drive's
# query itself; it still takes one as it is; and it looks in shared drives too, where a
# team's files live.

_URL = "https://www.googleapis.com/drive/v3/files"
_KINDS = {
    "doc": "application/vnd.google-apps.document",
    "sheet": "application/vnd.google-apps.spreadsheet",
    "slides": "application/vnd.google-apps.presentation",
    "folder": "application/vnd.google-apps.folder",
    "pdf": "application/pdf",
}


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _quoted(text: str) -> str:
    """A value as Drive's query language wants it: in single quotes, its own escaped."""
    return "'" + str(text).strip().replace("\\", "\\\\").replace("'", "\\'") + "'"


async def google_drive_search_files(
    name: str = "",
    text: str = "",
    kind: str = "",
    query: str = "",
    page_size: int = 20,
    page_token: str = "",
) -> dict:
    """Find files in the person's Google Drive, their shared drives included.

    Pass what is known, in plain words: `name` is all or part of the file's name ("board
    pack"); `text` is words that appear inside it; `kind` is "doc", "sheet", "slides",
    "pdf" or "folder". Given together they must all hold. Capitals do not matter. Files
    in the trash are left out. For anything else, `query` takes Drive's own query
    language and is used as it is (`modifiedTime > '2026-11-01T00:00:00'`,
    `'me' in owners`). `page_size` is 1 to 50; when the answer has `next_page_token` there
    are more: call again with it as `page_token`.

    Returns `files`, most recently changed first (by relevance when `text` is given):
    each with `id` (what the reading tools take), `name`, `kind`, `modified`, `owner`,
    `link`, and `shared_drive` true for a file in a shared drive.
    https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list
    """
    wanted = str(kind or "").strip().lower()
    if wanted and wanted not in _KINDS:
        return {"success": False, "data": None,
                "error": 'kind is "doc", "sheet", "slides", "pdf" or "folder"'}
    parts = []
    if name and name.strip():
        parts.append(f"name contains {_quoted(name)}")
    if text and text.strip():
        parts.append(f"fullText contains {_quoted(text)}")
    if wanted:
        parts.append(f"mimeType = {_quoted(_KINDS[wanted])}")
    if query and query.strip():
        parts.append(f"({query.strip()})")
    if not parts:
        return {"success": False, "data": None,
                "error": "pass a name, words in the text, a kind, or a query"}
    if "trashed" not in str(query or ""):
        parts.append("trashed = false")
    params = {
        "q": " and ".join(parts),
        "pageSize": max(1, min(int(page_size or 20), 50)),
        "fields": ("nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,driveId,"
                   "owners(displayName,emailAddress))"),
        # without these three Drive answers from My Drive alone
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
        "corpora": "allDrives",
    }
    if "fullText" not in params["q"]:
        params["orderBy"] = "modifiedTime desc"  # Drive refuses a sort with a text search
    if page_token:
        params["pageToken"] = page_token
    resp = await nexus_call("GET", _URL, provider="google_drive", params=params)  # noqa: F821
    if not resp["ok"]:
        return {"success": False, "data": None,
                "error": f"Drive could not be searched: {_reason(resp)}"}
    data = resp["json"] or {}
    kinds = {v: k for k, v in _KINDS.items()}
    files = []
    for each in data.get("files") or []:
        owner = (each.get("owners") or [{}])[0]
        files.append({
            "id": each.get("id"),
            "name": each.get("name"),
            "kind": kinds.get(each.get("mimeType"), each.get("mimeType")),
            "modified": each.get("modifiedTime"),
            "owner": owner.get("emailAddress") or owner.get("displayName"),
            "link": each.get("webViewLink"),
            **({"shared_drive": True} if each.get("driveId") else {}),
        })
    out = {"files": files, "count": len(files), "searched": params["q"]}
    if data.get("nextPageToken"):
        out["next_page_token"] = data["nextPageToken"]
    if not files:
        out["note"] = "No file matches. Try fewer words, or part of the name."
    return {"success": True, "data": out, "error": None}
