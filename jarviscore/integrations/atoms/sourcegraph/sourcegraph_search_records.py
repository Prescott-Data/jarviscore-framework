from typing import Any, Dict, List, Optional

async def sourcegraph_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Sourcegraph GraphQL search. Official: https://docs.sourcegraph.com/api/graphql"""
    try:
        if not query:
            return _sgg_dataset([], 400, 'query is required')
        root, err = _sgg_root(base_url)
        if err:
            return _sgg_dataset([], 400, err)
        headers, aerr = _sgg_auth()
        if aerr:
            return _sgg_dataset([], 401, aerr)
        cap = min(max(int(limit or 25), 1), 500)
        q = query if 'count:' in str(query).lower() else '%s count:%d' % (query, cap)
        gql = {'query': 'query Search($q: String!) { search(query: $q, version: V2) { results { results { ... on Repository { name url } ... on FileMatch { file { path url } repository { name } } } } } }', 'variables': {'q': q}}
        resp = await nexus_call('POST', root, headers=headers, json=gql)
        try:
            body = resp['json'] if resp['content'] else {}
        except Exception:
            body = {}
        if resp['status_code'] >= 400:
            return _sgg_dataset([], resp['status_code'], _sgg_err(resp, body))
        if isinstance(body, dict) and body.get('errors'):
            return _sgg_dataset([], 400, _sgg_err(resp, body))
        data = body.get('data') if isinstance(body, dict) else {}
        search = data.get('search') if isinstance(data, dict) else {}
        results = search.get('results') if isinstance(search, dict) else {}
        rows = results.get('results') if isinstance(results, dict) else []
        records = [x for x in rows or [] if isinstance(x, dict)][:cap]
        return _sgg_dataset(records, resp['status_code'], 'ok')
    except Exception as e:
        return _sgg_dataset([], 500, str(e))

def _sgg_root(base_url):
    root = (base_url or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://sourcegraph.example.com)')
    if not root.endswith('/.api/graphql'):
        root = root + '/.api/graphql'
    return (root, None)

def _sgg_auth():
    return ({'Accept': 'application/json', 'Content-Type': 'application/json'}, None)

def _sgg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sgg_err(resp, body=None):
    if isinstance(body, dict):
        errs = body.get('errors')
        if isinstance(errs, list) and errs:
            return str(errs[0])[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]
