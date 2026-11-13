async def msgraph_list_mail_folders(parent_folder_id: str = "", page_size: int = 100, continuation_cursor: str = "", include_hidden: bool = False) -> dict:
    """List mail folders. https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders?view=graph-rest-1.0
    One page only: replay continuation_cursor unchanged until has_more is false.
    """
    from urllib.parse import quote, urlsplit, parse_qsl

    fields = ['id', 'displayName', 'parentFolderId', 'childFolderCount', 'totalItemCount', 'unreadItemCount', 'isHidden']
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

    def validate_cursor(value, expected_path):
        if not isinstance(value, str) or any(ord(c) <= 32 for c in value):
            raise ValueError("Invalid continuation cursor")
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com"
                or parsed.path != expected_path or parsed.fragment or not parsed.query):
            raise ValueError("Invalid continuation cursor")
        # Keep Graph's entire URL unchanged; never reconstruct a skip token.
        if any(key.lower() not in {
            "$skip", "$skiptoken", "$top", "$select", "$orderby", "$filter",
            "includehiddenfolders",
        } for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise ValueError("Invalid continuation cursor")
        return value

    try:
        path = f"/me/mailFolders/{segment(parent_folder_id)}/childFolders" if parent_folder_id else "/me/mailFolders"
        url = "https://graph.microsoft.com/v1.0" + path
        if type(page_size) is not int or not 1 <= page_size <= 1000:
            raise ValueError("Invalid page size")
        params = {"$top": page_size, "$select": ",".join(fields)}
        if type(include_hidden) is not bool:
            raise ValueError("Invalid include_hidden")
        params["includeHiddenFolders"] = "true" if include_hidden else "false"
        if continuation_cursor:
            url = validate_cursor(continuation_cursor, "/v1.0" + path)
            params = None
        elif continuation_cursor not in ("", None):
            raise ValueError("Invalid continuation cursor")
        response = await nexus_call("GET", url, params=params)
        status = response.get("status_code")
        if status != 200 or not response.get("ok"):
            return {"success": False, "data": None, "error": f"Microsoft Graph read failed (HTTP {status})"}
        payload = response.get("json")
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise ValueError("Malformed page")
        if any(not isinstance(item, dict) for item in payload["value"]):
            raise ValueError("Malformed page item")
        next_cursor = payload.get("@odata.nextLink")
        if next_cursor is not None:
            next_cursor = validate_cursor(next_cursor, "/v1.0" + path)
        data = {"items": [project(item) for item in payload["value"]],
                "continuation_cursor": next_cursor, "has_more": next_cursor is not None}
        return {"success": True, "data": data, "error": None}
    except Exception:
        # Provider errors can include bearer or preauthenticated URLs.
        return {"success": False, "data": None, "error": "Microsoft Graph read failed: invalid input, response, or transport failure"}
