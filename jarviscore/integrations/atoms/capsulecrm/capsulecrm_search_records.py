from typing import Any, Dict, List, Optional
CAPSULE_API = 'https://api.capsulecrm.com'

async def capsulecrm_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search Records via Capsule CRM API. Official: https://developer.capsulecrm.com/v2/operations/Party"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        api = _capsule_api_root(base_url)
        headers, auth_err = _capsule_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        records, status, message = await _capsule_search(f'{api}/parties/search', headers, query, limit, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _capsule_api_root(base_url):
    root = (base_url or CAPSULE_API).rstrip('/')
    if root.endswith('/api/v2'):
        return root
    if root.endswith('/api'):
        return root + '/v2'
    if '/api/v2' not in root:
        return root + '/api/v2'
    return root

def _capsule_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _capsule_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

async def _capsule_search(url, headers, query, limit, timeout, verify_ssl):
    records = []
    page = 1
    status = 0
    per_page = min(max(int(limit), 1), 100)
    while len(records) < limit:
        params = {'q': query, 'page': page, 'perPage': min(per_page, limit - len(records))}
        resp = await _capsule_get(url, headers, params, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = []
        if isinstance(data, dict):
            batch = data.get('parties') or data.get('results') or []
        elif isinstance(data, list):
            batch = data
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        if len(batch) < params['perPage']:
            break
        page += 1
        if page > 500:
            break
    return (records[:limit], status, 'ok')
