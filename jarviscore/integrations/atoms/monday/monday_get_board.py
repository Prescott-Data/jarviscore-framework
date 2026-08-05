import requests
from typing import Any, Dict, List, Optional

# monday.com GraphQL API — Official docs:
# https://developer.monday.com/api-reference/reference/boards


MONDAY_API = "https://api.monday.com/v2"



def monday_get_board(auth_info: dict, board_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get board by ID via GraphQL boards query. Official: https://developer.monday.com/api-reference/reference/boards"""
    try:
        if not board_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "board_id is required"}
        base, err = _md_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, aerr = _md_auth(auth_info)
        if aerr:
            return {"records": [], "data_count": 0, "status": 401, "message": aerr}
        q = "query($ids: [ID!]) { boards(ids: $ids) { id name state board_kind description url workspace_id columns { id title type } groups { id title } } }"
        resp = _md_gql(base, headers, q, {"ids": [str(board_id)]}, timeout, verify_ssl)
        data, status, msg = _md_parse(resp)
        if status >= 400 and not data:
            return {"records": [], "data_count": 0, "status": status, "message": msg}
        records = _md_records((data or {}).get("boards"))
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _md_root(base_url):
    root = (base_url or MONDAY_API).rstrip("/")
    if "monday.com" not in root:
        return None, "base_url must be https://api.monday.com/v2"
    if not root.endswith("/v2"):
        root = root + "/v2" if root.endswith("monday.com") or root.endswith("api.monday.com") else root
    return root, None


def _md_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.api_token is required"
    tok = str(token).strip()
    if tok.lower().startswith("bearer "):
        auth = tok
    else:
        auth = tok
    return {"Content-Type": "application/json", "Accept": "application/json", "Authorization": auth}, None


def _md_board_id(auth_info, payload=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    bid = payload.get("board_id") or auth_info.get("board_id")
    if bid in (None, ""):
        return None, "board_id is required (payload.board_id or auth_info.board_id)"
    return str(bid), None


def _md_gql(base, headers, query, variables, timeout, verify_ssl):
    return requests.post(base, headers=headers, json={"query": query, "variables": variables or {}}, timeout=timeout, verify=verify_ssl)


def _md_parse(resp):
    try:
        body = resp.json() if resp.text else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return None, resp.status_code, (resp.text or f"HTTP {resp.status_code}")[:1000]
    errors = body.get("errors")
    if errors:
        msg = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])
        return body.get("data"), 400, msg
    return body.get("data") or {}, resp.status_code, "ok"


def _md_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _md_records(items):
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    if isinstance(items, dict):
        return [items]
    return []


def _md_provision(data, key, fallback_id=None):
    obj = (data or {}).get(key) if isinstance(data, dict) else None
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    if isinstance(obj, dict):
        pid = obj.get("id") or fallback_id
        ids = [pid] if pid not in (None, "") else []
        return {"records": [obj], "data_count": 1, "status": 200, "message": "ok", "provision_ids": ids}
    if obj is True or obj is not None:
        ids = [fallback_id] if fallback_id not in (None, "") else []
        rec = {"id": fallback_id, "success": True} if ids else {"success": True}
        return {"records": [rec], "data_count": 1, "status": 200, "message": "ok", "provision_ids": ids}
    return {"records": [], "data_count": 0, "status": 400, "message": "mutation returned no data", "provision_ids": []}


def _md_items_page(base, headers, board_id, limit, query_params, timeout, verify_ssl):
    cap = _md_cap(limit)
    records = []
    cursor = None
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        batch_size = min(cap - len(records), 100)
        if cursor:
            q = "query($cursor: String!, $limit: Int!) { next_items_page(cursor: $cursor, limit: $limit) { cursor items { id name state created_at updated_at url } } }"
            vars_ = {"cursor": cursor, "limit": batch_size}
        else:
            q = "query($board_id: [ID!], $limit: Int!, $query_params: ItemsQuery) { boards(ids: $board_id) { items_page(limit: $limit, query_params: $query_params) { cursor items { id name state created_at updated_at url } } } }"
            vars_ = {"board_id": [str(board_id)], "limit": batch_size, "query_params": query_params}
        resp = _md_gql(base, headers, q, vars_, timeout, verify_ssl)
        data, status, msg = _md_parse(resp)
        if status >= 400 and not data:
            return records, status, msg
        if cursor:
            page = (data or {}).get("next_items_page") or {}
        else:
            boards = (data or {}).get("boards") or []
            page = boards[0].get("items_page") if boards and isinstance(boards[0], dict) else {}
        items = _md_records((page or {}).get("items"))
        records.extend(items)
        cursor = (page or {}).get("cursor")
        if not items or not cursor:
            break
    return records[:cap], status, "ok"
