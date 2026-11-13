async def msgraph_download_message(message_id: str) -> dict:
    """Download message. https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
    Return original Graph $value bytes losslessly as base64; never follow redirects.
    """
    from urllib.parse import quote
    import base64

    def segment(value):
        if not isinstance(value, str) or not value or value in {".", ".."}:
            raise ValueError("Invalid identifier")
        return quote(value, safe="")

    try:
        path = f"/me/messages/{segment(message_id)}/$value"
        url = "https://graph.microsoft.com/v1.0" + path
        response = await nexus_call("GET", url)
        status = response.get("status_code")
        if status != 200 or not response.get("ok"):
            return {"success": False, "data": None, "error": f"Microsoft Graph read failed (HTTP {status})"}
        content = response.get("content")
        # The shipped sandbox RPC transports bytes in this exact envelope.
        if isinstance(content, dict) and set(content) == {"__bytes__"}:
            content = base64.b64decode(content["__bytes__"], validate=True)
        if not isinstance(content, bytes):
            raise ValueError("Original bytes unavailable")
        data = {"content_base64": base64.b64encode(content).decode("ascii"),
                "byte_count": len(content)}
        return {"success": True, "data": data, "error": None}
    except Exception:
        # Provider errors can include bearer or preauthenticated URLs.
        return {"success": False, "data": None, "error": "Microsoft Graph read failed: invalid input, response, or transport failure"}
