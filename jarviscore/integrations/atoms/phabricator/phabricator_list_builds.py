import requests
from typing import Any, Dict, List, Optional


def phabricator_list_builds(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List Harbormaster builds via harbormaster.build.search. Official: https://secure.phabricator.com/conduit/"""
    try:
        auth_info = auth_info or {}
        params = {"queryKey": auth_info.get("query_key") or auth_info.get("queryKey") or "all"}
        constraints = auth_info.get("constraints")
        if isinstance(constraints, dict):
            params["constraints"] = constraints
        records, status, msg = _ph_search("harbormaster.build.search", base_url, auth_info, params, limit, timeout, verify_ssl)
        return _ph_dataset(records, status, msg)
    except Exception as e:
        return _ph_dataset([], 500, str(e))


# Phabricator Conduit API — Official docs: https://secure.phabricator.com/conduit/


def _ph_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("phabricator_url") or auth_info.get("conduit_uri") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://phabricator.example.com)"
    return root, None


def _ph_token(auth_info):
    auth_info = auth_info or {}
    return (
        auth_info.get("api_key")
    )


def _ph_cap(limit):
    return min(max(int(limit or 25), 1), 1000)


def _ph_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _ph_provision(result, status, msg, fallback_id=None):
    obj = result if isinstance(result, dict) else {}
    inner = obj.get("object") if isinstance(obj.get("object"), dict) else obj
    pid = None
    if isinstance(inner, dict):
        pid = inner.get("id") or inner.get("phid")
    if pid in (None, "") and fallback_id not in (None, ""):
        pid = fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = dict(inner) if isinstance(inner, dict) and inner else ({"id": pid, "phid": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _ph_rows(result):
    rows = []
    if not isinstance(result, dict):
        return rows
    for item in result.get("data") or []:
        if not isinstance(item, dict):
            continue
        row = {"id": item.get("id"), "phid": item.get("phid")}
        fields = item.get("fields")
        if isinstance(fields, dict):
            row.update(fields)
        rows.append(row)
    return rows


def _ph_err(body, resp):
    if isinstance(body, dict):
        info = body.get("error_info") or body.get("error_code") or body.get("errorMessage")
        if info:
            return str(info)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _ph_conduit(method, params, base_url, auth_info, timeout=30, verify_ssl=True):
    import json
    root, err = _ph_root(base_url, auth_info)
    if err:
        return None, None, 400, err
    tok = _ph_token(auth_info)
    if not tok:
        return None, None, 401, "auth_info.api_key is required"
    form = {"api.token": str(tok).strip()}
    for key, val in (params or {}).items():
        if val is None:
            continue
        if isinstance(val, (dict, list)):
            form[key] = json.dumps(val)
        else:
            form[key] = str(val)
    url = root + "/api/" + method
    resp = requests.post(url, data=form, timeout=timeout, verify=verify_ssl)
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _ph_err(body, resp)
    if isinstance(body, dict) and body.get("error_code"):
        return resp, body, 400, _ph_err(body, resp)
    result = body.get("result") if isinstance(body, dict) else None
    return resp, result, 200, "ok"


def _ph_search(method, base_url, auth_info, base_params, limit, timeout, verify_ssl):
    cap = _ph_cap(limit)
    records = []
    after = None
    status = 200
    msg = "ok"
    while len(records) < cap:
        params = dict(base_params or {})
        params["limit"] = min(100, cap - len(records))
        if after:
            params["after"] = after
        resp, result, status, msg = _ph_conduit(method, params, base_url, auth_info, timeout, verify_ssl)
        if status >= 400:
            return records[:cap], status, msg
        batch = _ph_rows(result)
        records.extend(batch)
        cursor = result.get("cursor") if isinstance(result, dict) else None
        after = cursor.get("after") if isinstance(cursor, dict) else None
        if not after or not batch:
            break
    return records[:cap], status, msg


def _ph_id_constraints(obj_id):
    sid = str(obj_id).strip()
    if sid.upper().startswith("PHID-"):
        return {"phids": [sid]}
    try:
        return {"ids": [int(sid)]}
    except Exception:
        return {"phids": [sid]}


def _ph_payload_transactions(payload, mapping):
    if not isinstance(payload, dict) or not payload:
        return None, "payload is required"
    if isinstance(payload.get("transactions"), list):
        return payload["transactions"], None
    tx = []
    for key, ttype in mapping.items():
        if key in payload and payload[key] is not None:
            tx.append({"type": ttype, "value": payload[key]})
    if not tx:
        return None, "payload must include transactions or supported fields"
    return tx, None
