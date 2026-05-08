def sendgrid_send_email(auth_info: dict, to: str, subject: str, body: str, from_email: str = "agents@example.com", body_type: str = "text/plain") -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('api_key', '')}", "Content-Type": "application/json"}
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": body_type, "value": body}]
    }
    resp = requests.post("https://api.sendgrid.com/v3/mail/send", headers=_h, json=payload, timeout=30)
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"SendGrid error: {resp.status_code} {resp.text}")
    return {"success": True, "to": to, "subject": subject}
