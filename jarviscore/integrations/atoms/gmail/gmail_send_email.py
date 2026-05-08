def gmail_send_email(auth_info: dict, to: str, subject: str, body: str, body_type: str = "text/plain") -> dict:
    import requests, base64, json
    _base = "https://gmail.googleapis.com/gmail/v1/users/me"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    raw = f"To: {to}\r\nSubject: {subject}\r\nContent-Type: {body_type}; charset=utf-8\r\nMIME-Version: 1.0\r\n\r\n{body}"
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()
    resp = requests.post(f"{_base}/messages/send", headers=_h, json={"raw": encoded}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "message_id": data.get("id"), "thread_id": data.get("threadId")}
