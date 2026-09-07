from typing import Any, Dict, List, Optional
CAPSULE_API = 'https://api.capsulecrm.com'

async def capsulecrm_list_contacts(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List Contacts via Capsule CRM API. Official: https://developer.capsulecrm.com/v2/operations/Party"""
    try:
        api = _capsule_api_root(base_url)
        (headers, auth_err) = _capsule_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        (records, status, message) = await _capsule_paginate(f'{api}/parties', headers, limit, timeout, verify_ssl, party_type='person')
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

def _capsule_batch_from(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ('parties', 'opportunities', 'results'):
        if isinstance(data.get(key), list):
            return data[key]
    if isinstance(data.get('party'), dict):
        return [data['party']]
    if isinstance(data.get('opportunity'), dict):
        return [data['opportunity']]
    return []

async def _capsule_paginate(url, headers, limit, timeout, verify_ssl, extra=None, party_type=None):
    records = []
    page = 1
    status = 0
    extra = extra or {}
    per_page = min(max(int(limit), 1), 100)
    want = party_type.lower() if party_type else None
    while len(records) < limit:
        params = {'page': page, 'perPage': per_page}
        params.update(extra)
        resp = await _capsule_get(url, headers, params, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = _capsule_batch_from(data)
        if not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                continue
            if want and (item.get('type') or '').lower() != want:
                continue
            records.append(item)
            if len(records) >= limit:
                break
        if len(batch) < params['perPage']:
            break
        page += 1
        if page > 500:
            break
    return (records[:limit], status, 'ok')
