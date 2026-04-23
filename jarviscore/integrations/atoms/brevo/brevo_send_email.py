def brevo_send_email(auth_info: dict, to: str, subject: str, body: str, from_email: str = "agents@example.com", from_name: str = "AI Agent") -> dict:
    import requests
    _h = {"api-key": auth_info.get("api_key", ""), "Content-Type": "application/json"}
    payload = {
        "sender": {"name": from_name, "email": from_email},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body
    }
    resp = requests.post("https://api.brevo.com/v3/smtp/email", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "message_id": data.get("messageId"), "to": to}
