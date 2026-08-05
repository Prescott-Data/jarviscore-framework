import requests
from typing import Any, Dict, List, Optional

# Places API (New) searchText — https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/searchText
_PLACES_API_ROOT = "https://places.googleapis.com/v1"


def google_maps_search_records(auth_info: dict, text_query: str, max_results: int = 20, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Places API searchText (pageSize max 20, pageToken pagination). Official: https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/searchText"""
    try:
        api, err = _places_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        if not text_query:
            return {"records": [], "data_count": 0, "status": 400, "message": "text_query is required"}
        field_mask = "places.id,places.displayName,places.formattedAddress,places.location"
        headers, auth_err = _places_auth(auth_info, field_mask, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        url = f"{api}/places:searchText"
        cap = min(max(int(max_results or 20), 1), 100)
        records: List[Dict[str, Any]] = []
        page_token = None
        status = 0
        while len(records) < cap:
            page_size = min(20, cap - len(records))  # official max pageSize is 20
            payload: Dict[str, Any] = {"textQuery": text_query, "pageSize": page_size}
            if page_token:
                payload["pageToken"] = page_token
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout, verify=verify_ssl)
            status = resp.status_code
            if status >= 400:
                return {"records": records, "data_count": len(records), "status": status, "message": resp.text[:1000]}
            data = resp.json() if resp.text else {}
            places = data.get("places") if isinstance(data, dict) else None
            if isinstance(places, list):
                for item in places:
                    if isinstance(item, dict):
                        records.append(item)
                        if len(records) >= cap:
                            break
            page_token = data.get("nextPageToken") if isinstance(data, dict) else None
            if not page_token or len(records) >= cap:
                break
        return {"records": records[:cap], "data_count": len(records[:cap]), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _places_api_root(base_url: str):
    root = (base_url or _PLACES_API_ROOT).rstrip("/")
    if "places.googleapis.com" not in root:
        return None, "base_url must be Places API root (https://places.googleapis.com/v1)"
    return root, None


def _places_headers(auth_info: Optional[Dict[str, Any]], field_mask: str, json_body: bool = False) -> Dict[str, str]:
    auth_info = auth_info or {}
    headers = {"Accept": "application/json", "X-Goog-FieldMask": field_mask}
    if json_body:
        headers["Content-Type"] = "application/json"
    api_key = auth_info.get("api_key")
    if api_key:
        headers["X-Goog-Api-Key"] = str(api_key)
    return headers
