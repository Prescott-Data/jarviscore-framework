import requests
from typing import Any, Dict, List, Optional

# POST /v2/objects/people/records — https://docs.attio.com/rest-api/endpoint-reference/records/create-a-record
_ATTIO_HOST = "https://api.attio.com"
_OBJECT_SLUGS = {
    "contacts": "people",
    "contact": "people",
    "people": "people",
    "accounts": "companies",
    "account": "companies",
    "companies": "companies",
    "deals": "deals",
    "deal": "deals",
}


def attio_create_contact(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create person record (POST /v2/objects/people/records). Official: https://docs.attio.com/rest-api/endpoint-reference/records/create-a-record"""
    try:
        if not base_url:
            return _attio_provision([], 400, "base_url is required")
        api_root, root_err = _attio_api_root(base_url)
        if root_err:
            return _attio_provision([], 400, root_err)
        auth_err = _attio_auth_err(auth_info)
        if auth_err:
            return _attio_provision([], 401, auth_err)
        headers = _attio_headers(auth_info, json_body=True)
        resp = requests.post(
            f"{api_root}/objects/people/records",
            headers=headers,
            json=_attio_wrap_values(payload),
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {}
        if status >= 400:
            return _attio_provision([], status, _attio_err(resp))
        rec = _attio_record(body)
        records = [rec] if rec else []
        return _attio_provision(records, status, "ok", _attio_provision_ids(body))
    except Exception as e:
        return _attio_provision([], 500, str(e))



def _attio_api_root(base_url: str):
    root = base_url.rstrip("/")
    if root.endswith("/v2"):
        return root, None
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    if root == _ATTIO_HOST or _host_is(root, "api.attio.com"):
        return _ATTIO_HOST + "/v2", None
    return None, "base_url must be https://api.attio.com"


def _attio_headers(auth_info, json_body: bool = False):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def _attio_auth_err(auth_info):
    auth_info = auth_info or {}
    if auth_info.get("api_key"):
        return None
    return "auth_info requires access_token or api_key"


def _attio_object_slug(kind: str) -> str:
    slug = _OBJECT_SLUGS.get(str(kind or "").lower())
    if not slug:
        raise ValueError(f"unsupported object kind: {kind}")
    return slug


def _attio_records(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        batch = data.get("data")
        if isinstance(batch, list):
            return batch
        if batch is not None:
            return [batch]
    return []


def _attio_query_records(api_root, object_slug, headers, limit, timeout, verify_ssl, extra_body=None):
    records: List[Dict[str, Any]] = []
    offset = 0
    status = 0
    page_size = min(max(limit, 1), 500)
    extra_body = dict(extra_body or {})
    while len(records) < limit:
        body = {"limit": min(page_size, limit - len(records)), "offset": offset}
        body.update(extra_body)
        resp = requests.post(
            f"{api_root}/objects/{object_slug}/records/query",
            headers=headers,
            json=body,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        batch = _attio_records(resp.json())
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        if len(batch) < body["limit"]:
            break
        offset += len(batch)
        if offset > 100000:
            break
    return records[:limit], status, "ok"


def _attio_wrap_values(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload
    if isinstance(payload, dict) and "values" in payload:
        return {"data": payload}
    return {"data": {"values": payload or {}}}


def _attio_provision_id(body):
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, dict):
        rid = data.get("id")
        if isinstance(rid, dict) and rid.get("record_id") not in (None, ""):
            return [rid["record_id"]]
        if data.get("record_id") not in (None, ""):
            return [data["record_id"]]
    rid = body.get("id")
    if isinstance(rid, dict) and rid.get("record_id") not in (None, ""):
        return [rid["record_id"]]
    return []


def _attio_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {
        "records": recs,
        "data_count": len(recs),
        "status": status,
        "message": msg,
        "provision_ids": ids,
    }


def _attio_provision_ids(body, fallback_id=None):
    ids = _attio_provision_id(body)
    if ids:
        return [str(x) for x in ids]
    if fallback_id not in (None, ""):
        return [str(fallback_id)]
    return []


def _attio_record(body):
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return {}


def _attio_err(resp):
    return (resp.text if resp is not None else "request failed")[:1000]


def _attio_search_filter(query: str):
    q = query.strip()
    return {
        "$or": [
            {"name": {"full_name": {"$contains": q}}},
            {"description": {"value": {"$contains": q}}},
            {"email_addresses": {"email_address": {"$contains": q}}},
            {"domains": {"domain": {"$contains": q}}},
        ]
    }


def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or "").strip()
    if "://" not in u:
        u = "https://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)
