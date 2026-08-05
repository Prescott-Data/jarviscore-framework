import requests
from typing import Any, Dict, List, Optional


def sourcegraph_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Sourcegraph GraphQL search. Official: https://docs.sourcegraph.com/api/graphql"""
    try:
        if not query:
            return _sgg_dataset([], 400, "query is required")
        root, err = _sgg_root(base_url, auth_info)
        if err:
            return _sgg_dataset([], 400, err)
        headers, aerr = _sgg_auth(auth_info)
        if aerr:
            return _sgg_dataset([], 401, aerr)
        cap = min(max(int(limit or 25), 1), 500)
        # Sourcegraph's GraphQL `search` field takes no `first` argument; result count is controlled via the `count:` filter in the query string.
        q = query if "count:" in str(query).lower() else "%s count:%d" % (query, cap)
        gql = {
            "query": "query Search($q: String!) { search(query: $q, version: V2) { results { results { ... on Repository { name url } ... on FileMatch { file { path url } repository { name } } } } } }",
            "variables": {"q": q},
        }
        resp = requests.post(root, headers=headers, json=gql, timeout=timeout, verify=verify_ssl)
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {}
        if resp.status_code >= 400:
            return _sgg_dataset([], resp.status_code, _sgg_err(resp, body))
        if isinstance(body, dict) and body.get("errors"):
            return _sgg_dataset([], 400, _sgg_err(resp, body))
        data = body.get("data") if isinstance(body, dict) else {}
        search = data.get("search") if isinstance(data, dict) else {}
        results = search.get("results") if isinstance(search, dict) else {}
        rows = results.get("results") if isinstance(results, dict) else []
        records = [x for x in (rows or []) if isinstance(x, dict)][:cap]
        return _sgg_dataset(records, resp.status_code, "ok")
    except Exception as e:
        return _sgg_dataset([], 500, str(e))


# Sourcegraph GraphQL API — Official docs: https://docs.sourcegraph.com/api/graphql


def _sgg_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("sourcegraph_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://sourcegraph.example.com)"
    if not root.endswith("/.api/graphql"):
        root = root + "/.api/graphql"
    return root, None


def _sgg_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.access_token is required"
    t = str(token).strip()
    return {"Accept": "application/json", "Authorization": t if t.lower().startswith("token ") else "token " + t, "Content-Type": "application/json"}, None


def _sgg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sgg_err(resp, body=None):
    if isinstance(body, dict):
        errs = body.get("errors")
        if isinstance(errs, list) and errs:
            return str(errs[0])[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]
