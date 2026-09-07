from typing import Any, Dict, List, Optional
WIX_API = 'https://www.wixapis.com'

async def wix_stores_list_customers(site_id: str='', limit: int=100, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """wix_stores API: list customers. Official: https://dev.wix.com/docs/rest/business-solutions/stores"""
    try:
        (root, err) = _wx_root(base_url)
        if err:
            return _wx_dataset([], 400, err)
        (headers, aerr) = _wx_headers(site_id)
        if aerr:
            return _wx_dataset([], 401, aerr)
        body = {'query': {'paging': {'limit': limit}}}
        resp = await nexus_call('POST', f'{root}/contacts/v4/contacts/query', headers=headers, json=body)
        if resp['status_code'] >= 400:
            return _wx_dataset([], resp['status_code'], _wx_err(resp))
        return _wx_dataset(_wx_list(resp['json'] if resp['content'] else {}), resp['status_code'], 'ok')
    except Exception as e:
        return _wx_dataset([], 500, str(e))

def _wx_root(base_url):
    raw = (base_url or None or WIX_API).strip().rstrip('/')
    if 'wixapis.com' not in raw:
        return (None, 'base_url must be https://www.wixapis.com')
    return (raw[:raw.index('wixapis.com') + len('wixapis.com')], None)

def _wx_headers(site_id):
    sid = site_id or None
    if not sid:
        return (None, 'site_id is required (wix-site-id header for site-level calls)')
    return ({'wix-site-id': str(sid), 'Content-Type': 'application/json', 'Accept': 'application/json'}, None)

def _wx_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _wx_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _wx_list(data):
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        return [data] if data else []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []
