from typing import Any, Dict, List, Optional
KM_API = 'https://query.kissmetrics.io/v3'

async def kissmetrics_search_records(query: str, product_id: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search Kissmetrics events client-side after listing (GET /v3/products/{product_id}/events). Official: https://support.kissmetrics.io/reference/fetch-events"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        pid = _km_product_id(product_id)
        if not pid:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'product_id is required'}
        api, err = _km_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, basic, auth_err = _km_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await _km_get(f'{api}/products/{pid}/events', headers, basic, {'limit': min(max(int(limit or 25), 1), 50)}, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        needle = query.lower()
        matched = []
        for item in _km_records(resp['json'] if resp['body'] else {}):
            if isinstance(item, dict) and needle in str(item).lower():
                matched.append(item)
                if len(matched) >= limit:
                    break
        return {'records': matched, 'data_count': len(matched), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _km_api_root(base_url):
    root = (base_url or KM_API).rstrip('/')
    if 'kissmetrics.io' not in root:
        return (None, 'base_url must be https://query.kissmetrics.io/v3')
    if not root.endswith('/v3'):
        if root.endswith('/v3.0'):
            root = root[:-2]
        elif '/v3' not in root:
            root = f'{root}/v3'
    return (root, None)

def _km_auth():
    return ({'Accept': 'application/json'}, None, None)

async def _km_get(url, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _km_records(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('events', 'reports', 'data', 'results'):
            batch = data.get(key)
            if isinstance(batch, list):
                return batch
    return []

def _km_product_id(product_id=None):
    pid = product_id or None or None
    return str(pid).strip() if pid not in (None, '') else None
