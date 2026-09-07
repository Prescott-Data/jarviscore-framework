from typing import Any, Dict, List, Optional
WIX_API = 'https://www.wixapis.com'

async def wix_stores_get_product(product_id: str, site_id: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """wix_stores API: get product. Official: https://dev.wix.com/docs/rest/business-solutions/stores"""
    try:
        if not product_id:
            return _wx_dataset([], 400, 'product_id is required')
        (root, err) = _wx_root(base_url)
        if err:
            return _wx_dataset([], 400, err)
        (headers, aerr) = _wx_headers(site_id)
        if aerr:
            return _wx_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/stores/v1/products/{product_id}', headers=headers)
        if resp['status_code'] >= 400:
            return _wx_dataset([], resp['status_code'], _wx_err(resp))
        return _wx_dataset(_wx_obj(resp['json'] if resp['content'] else {}, 'product'), resp['status_code'], 'ok')
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

def _wx_obj(data, key):
    if isinstance(data, dict):
        if isinstance(data.get(key), dict):
            return [data[key]]
        return [data] if data else []
    return []
