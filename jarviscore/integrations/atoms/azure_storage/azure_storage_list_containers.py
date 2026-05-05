def azure_storage_list_containers(auth_info: dict, account_name: str) -> dict:
    import requests
    import xml.etree.ElementTree as ET
    try:
        access_token = _get_nexus_token(auth_info)
    except Exception as e:
        return {"success": False, "data": None, "error": f"Auth error: {str(e)}"}

    try:
        resp = requests.get(
            f"https://{account_name}.blob.core.windows.net/",
            headers={"Authorization": f"Bearer {access_token}", "x-ms-version": "2020-10-02"},
            params={"comp": "list"},
            timeout=30
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"List containers failed: {resp.status_code} {resp.text}"}

        root = ET.fromstring(resp.text)
        containers = [c.find("Name").text for c in root.findall(".//Container")]
        return {"success": True, "data": {"containers": containers, "count": len(containers)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
