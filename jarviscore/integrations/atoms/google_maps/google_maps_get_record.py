import requests
from typing import Any, Dict, List, Optional

# Places API get — https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/get — https://developers.google.com/maps/documentation/places/web-service
_PLACES_API_ROOT = "https://places.googleapis.com/v1"


def google_maps_get_record(auth_info: dict, place_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """GET places/{placeId} with FieldMask header. Official: https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/get"""
    try:
        api, err = _places_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        if not place_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "place_id is required"}
        pid = place_id if place_id.startswith("places/") else f"places/{place_id}"
        field_mask = "id,displayName,formattedAddress,location,internationalPhoneNumber,websiteUri"
        headers, auth_err = _places_auth(auth_info, field_mask)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        url = f"{api}/{pid}"
        resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = [data] if isinstance(data, dict) and data else []
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
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
