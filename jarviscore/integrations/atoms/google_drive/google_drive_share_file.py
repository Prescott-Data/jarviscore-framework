ATOM_POLICY = {
    "effect": "notify",
    "approval": "required",
    "idempotency_fields": ["file_id", "name", "email", "role"],
    "consequence": (
        "Gives one person access to one Google Drive file; Google emails them the link."
    ),
}

# The call names the file as well as its id, so what the person approves says which file
# and to whom, and the file is read first: when the name passed is not the file's own,
# nobody is given anything.

_API = "https://www.googleapis.com/drive/v3/files"
_ROLES = {"reader": "view", "commenter": "comment on", "writer": "edit"}


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _same(a: str, b: str) -> bool:
    """Whether two names are the same but for capitals and spacing."""
    return " ".join(str(a or "").lower().split()) == " ".join(str(b or "").lower().split())


def _consequence(params: dict) -> str:
    """What the approval request says this call does, from its arguments alone."""
    role = str(params.get("role") or "reader").strip().lower()
    may = _ROLES.get(role, role)
    note = " ".join(str(params.get("message") or "").split())[:300]
    said = f' with this note: "{note}"' if note else ""
    return (f'Lets {str(params.get("email") or "?").strip().lower()} {may} the Drive file '
            f'"{params.get("name") or "?"}". Google emails them the link{said}. They keep '
            "that access until it is removed in Drive.")


async def google_drive_share_file(
    file_id: str, name: str, email: str, role: str = "reader", message: str = ""
) -> dict:
    """Share one Drive file with one person. Google emails them the link. It waits for
    approval, which names the file, the recipient and what they may do.

    `file_id` is the file's `id` and `name` its name, both as google_drive_search_files or
    google_drive_create_document returned them: the call is refused when they do not
    belong together. `email` is the one person's address. `role` is "reader" (view),
    "commenter" or "writer" (edit). `message` is an optional note in Google's email.

    Under the drive.file scope only a file this application created can be shared; for any
    other, Google refuses, and the answer says so: its owner shares that one themselves.
    Returns `shared_with`, `role`, `name` and `link`.
    https://developers.google.com/workspace/drive/api/reference/rest/v3/permissions/create
    """
    file_id, person = str(file_id or "").strip(), str(email or "").strip().lower()
    role = str(role or "reader").strip().lower()
    if not file_id or not str(name or "").strip():
        return {"success": False, "data": None,
                "error": "file_id and the file's name as listed are both needed"}
    if "@" not in person or " " in person or "," in person:
        return {"success": False, "data": None,
                "error": f"email is one address; got {email!r}"}
    if role not in _ROLES:
        return {"success": False, "data": None,
                "error": 'role is "reader", "commenter" or "writer"'}
    about = await nexus_call(  # noqa: F821
        "GET",
        f"{_API}/{file_id}",
        provider="google_drive",
        params={"fields": "id,name,webViewLink", "supportsAllDrives": "true"},
    )
    if not about["ok"]:
        return {"success": False, "data": None,
                "error": f"the file could not be found: {_reason(about)}"}
    file = about["json"] or {}
    if not _same(file.get("name"), name):
        return {"success": False, "data": None,
                "error": f"file {file_id} is named {file.get('name')!r}, not {name!r}; nobody "
                         "was given access. Pass the id and name of the same file."}
    params = {"sendNotificationEmail": "true", "supportsAllDrives": "true",
              "fields": "id,role,emailAddress"}
    if message and message.strip():
        params["emailMessage"] = message.strip()
    done = await nexus_call(  # noqa: F821
        "POST",
        f"{_API}/{file_id}/permissions",
        provider="google_drive",
        headers={"Content-Type": "application/json"},
        params=params,
        json={"type": "user", "role": role, "emailAddress": person},
    )
    if not done["ok"]:
        why = _reason(done)
        if done.get("status_code") in (403, 404):
            why += (". With the drive.file scope only a file this application created can "
                    "be shared; its owner shares any other themselves")
        return {"success": False, "data": None, "error": f"the file was not shared: {why}"}
    granted = done["json"] or {}
    return {
        "success": True,
        "data": {
            "shared_with": granted.get("emailAddress") or person,
            "role": granted.get("role") or role,
            "name": file.get("name"),
            "link": file.get("webViewLink"),
            "emailed": True,
        },
        "error": None,
    }
