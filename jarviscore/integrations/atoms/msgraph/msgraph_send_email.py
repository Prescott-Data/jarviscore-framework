def msgraph_send_email(auth_info: dict, to: list, subject: str, body: str, body_type: str = "Text", cc: list = None) -> dict:
    import requests
    # to and cc: list of email address strings
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        to_recipients = [{"emailAddress": {"address": addr}} for addr in to]
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": to_recipients
            }
        }
        if cc:
            payload["message"]["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

        resp = requests.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        if resp.status_code != 202:
            return {"success": False, "data": None, "error": f"Send email failed: {resp.status_code} {resp.text}"}

        return {"success": True, "data": {"sent": True, "to": to, "subject": subject}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
