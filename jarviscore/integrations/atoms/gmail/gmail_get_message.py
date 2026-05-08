def gmail_get_message(auth_info: dict, message_id: str) -> dict:
    import requests, base64
    _base = "https://gmail.googleapis.com/gmail/v1/users/me"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    resp = requests.get(f"{_base}/messages/{message_id}", headers=_h, params={"format": "full"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    # Decode body
    body = ""
    parts = data.get("payload", {}).get("parts", [])
    if parts:
        for part in parts:
            if part.get("mimeType") == "text/plain":
                bd = part.get("body", {}).get("data", "")
                if bd:
                    body = base64.urlsafe_b64decode(bd + "==").decode("utf-8", errors="ignore")
                    break
    else:
        bd = data.get("payload", {}).get("body", {}).get("data", "")
        if bd:
            body = base64.urlsafe_b64decode(bd + "==").decode("utf-8", errors="ignore")
    return {"success": True, "id": message_id, "subject": headers.get("Subject"), "from": headers.get("From"), "to": headers.get("To"), "date": headers.get("Date"), "body": body}
