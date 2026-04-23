def gmail_create_draft(auth_info: dict, to: str, subject: str, body: str) -> dict:
    import requests, base64
    _base = "https://gmail.googleapis.com/gmail/v1/users/me"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    raw = f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\nMIME-Version: 1.0\r\n\r\n{body}"
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()
    resp = requests.post(f"{_base}/drafts", headers=_h, json={"message": {"raw": encoded}}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "draft_id": data.get("id"), "message_id": data.get("message", {}).get("id")}
