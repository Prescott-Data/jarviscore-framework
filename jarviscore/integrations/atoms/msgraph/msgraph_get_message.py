async def msgraph_get_message(message_id: str) -> dict:
    """Get message. https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
    Return selected metadata only, without download URLs or credentials.
    """
    from urllib.parse import quote

    fields = ['id', 'subject', 'from', 'sender', 'toRecipients', 'ccRecipients', 'bccRecipients', 'receivedDateTime', 'sentDateTime', 'lastModifiedDateTime', 'hasAttachments', 'isRead', 'internetMessageId', 'parentFolderId', 'bodyPreview', 'body']
    def project(item):
        result = {key: item[key] for key in fields if key in item}
        nested = {
            "file": {"mimeType"}, "folder": {"childCount"},
            "parentReference": {"id", "driveId", "driveType"}, "deleted": {"state"},
            "body": {"content", "contentType"},
        }
        for key, allowed in nested.items():
            if key in result:
                value = result[key]
                if not isinstance(value, dict):
                    raise ValueError("Malformed metadata")
                result[key] = {k: v for k, v in value.items() if k in allowed}
        for key in ("from", "sender", "toRecipients", "ccRecipients", "bccRecipients"):
            if key in result:
                if result[key] is None:
                    continue
                many = key.endswith("Recipients")
                values = result[key] if many else [result[key]]
                if not isinstance(values, list):
                    raise ValueError("Malformed recipients")
                clean = []
                for value in values:
                    if not isinstance(value, dict) or not isinstance(value.get("emailAddress"), dict):
                        raise ValueError("Malformed recipient")
                    clean.append({"emailAddress": {k: v for k, v in value["emailAddress"].items() if k in {"name", "address"}}})
                result[key] = clean if many else clean[0]
        if "@odata.type" in item and item["@odata.type"] in {
            "#microsoft.graph.fileAttachment", "#microsoft.graph.itemAttachment",
            "#microsoft.graph.referenceAttachment",
        }:
            result["@odata.type"] = item["@odata.type"]
        return result

    def segment(value):
        if not isinstance(value, str) or not value or value in {".", ".."}:
            raise ValueError("Invalid identifier")
        return quote(value, safe="")

    try:
        path = f"/me/messages/{segment(message_id)}"
        url = "https://graph.microsoft.com/v1.0" + path
        response = await nexus_call("GET", url, params={"$select": ",".join(fields)})
        status = response.get("status_code")
        if status != 200 or not response.get("ok"):
            return {"success": False, "data": None, "error": f"Microsoft Graph read failed (HTTP {status})"}
        payload = response.get("json")
        if not isinstance(payload, dict) or not payload.get("id"):
            raise ValueError("Malformed metadata")
        data = project(payload)
        return {"success": True, "data": data, "error": None}
    except Exception:
        # Provider errors can include bearer or preauthenticated URLs.
        return {"success": False, "data": None, "error": "Microsoft Graph read failed: invalid input, response, or transport failure"}
