from typing import Any, Dict, List, Optional
CLOSE_API = 'https://api.close.com/api/v1'

async def close_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search leads in Close CRM via POST /data/search/ advanced filter. HTTP Basic API key (username, empty password). Official: https://developer.close.com/"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        api = _close_api_root(base_url)
        headers, basic, auth_err = _close_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        body = _close_search_query(query, limit)
        resp = await _close_post_json(f'{api}/data/search/', headers, basic, body, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _close_records_from(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _close_api_root(base_url):
    root = (base_url or CLOSE_API).rstrip('/')
    if root.endswith('/api/v1'):
        return root
    if root.endswith('/api'):
        return root + '/v1'
    if _host_is(root, 'api.close.com') and '/api/v1' not in root:
        return root + '/api/v1' if not root.endswith('/v1') else root
    if '/api/v1' not in root:
        return root + '/api/v1'
    return root

def _close_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (None, None, 'auth_info requires api_key (HTTP Basic, empty password)')

async def _close_post_json(url, headers, basic, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

def _close_records_from(data, single=False):
    if single:
        if isinstance(data, dict):
            if isinstance(data.get('data'), dict):
                return [data['data']]
            if data.get('id') is not None:
                return [data]
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get('data')
        if isinstance(items, list):
            return items
    return []

def _close_search_query(query, limit):
    return {'query': {'type': 'and', 'queries': [{'type': 'object_type', 'object_type': 'lead'}, {'type': 'text', 'value': query, 'mode': 'full_words'}]}, '_limit': min(max(int(limit), 1), 100)}

def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or '').strip()
    if '://' not in u:
        u = 'https://' + u
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return any((host == d or host.endswith('.' + d) for d in domains))
