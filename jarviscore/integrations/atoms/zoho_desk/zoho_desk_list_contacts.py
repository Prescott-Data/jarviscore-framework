from typing import Any, Dict, List, Optional
ZD_API = 'https://desk.zoho.com/api/v1'

async def zoho_desk_list_contacts(org_id: str='', limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """zoho_desk API: list contacts. Official: https://desk.zoho.com/DeskAPIDocument"""
    try:
        (root, err) = _zd_root(base_url)
        if err:
            return _zd_dataset([], 400, err)
        (headers, aerr) = _zd_headers(org_id)
        if aerr:
            return _zd_dataset([], 401, aerr)
        (records, status, msg) = await _zd_paginate(f'{root}/contacts', headers, limit, timeout, verify_ssl)
        return _zd_dataset(records, status, msg)
    except Exception as e:
        return _zd_dataset([], 500, str(e))

def _zd_root(base_url):
    root = (base_url or None or ZD_API).strip().rstrip('/')
    if 'zoho.' not in root:
        return (None, 'base_url must be https://desk.zoho.com/api/v1')
    return (root, None)

def _zd_headers(org_id=''):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if org_id:
        headers['orgId'] = str(org_id)
    return (headers, None)

def _zd_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _zd_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

async def _zd_paginate(url, headers, limit, timeout, verify_ssl, extra=None):
    records: List[Dict[str, Any]] = []
    cap = min(max(int(limit or 25), 1), 100)
    frm = 1
    status = 0
    while len(records) < cap:
        params = dict(extra or {})
        params['from'] = frm
        params['limit'] = min(cap - len(records), 100)
        resp = await nexus_call('GET', url, headers=headers, params=params)
        status = resp['status_code']
        if status == 204:
            break
        if status >= 400:
            return (records, status, _zd_err(resp))
        data = resp['json'] if resp['content'] else {}
        batch = data.get('data') if isinstance(data, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        records.extend([r for r in batch if isinstance(r, dict)])
        if len(batch) < params['limit']:
            break
        frm += len(batch)
    return (records[:cap], status, 'ok')
