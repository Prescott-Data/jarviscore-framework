from typing import Any, Dict, List, Optional
_ETSY_API_SUFFIX = '/v3/application'

async def etsy_get_order(shop_id: str, order_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get shop receipt (GET /v3/application/shops/{shop_id}/receipts/{receipt_id}). order_id is receipt_id. Requires x-api-key (keystring:shared_secret) and OAuth Bearer token per Etsy Open API v3. Official: https://developers.etsy.com/documentation/reference#operation/getShopReceipt"""
    try:
        if not order_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'order_id (receipt_id) is required'}
        (api, err) = _etsy_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (sid, err) = _etsy_shop_id(shop_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _etsy_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        receipt_id = str(order_id).strip()
        resp = await nexus_call('GET', f'{api}/shops/{sid}/receipts/{receipt_id}', headers=headers)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _etsy_results(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _etsy_api_root(base_url: str):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required (https://openapi.etsy.com/v3/application)')
    if not root.endswith('/v3/application'):
        if root.endswith('/v3'):
            root = f'{root}/application'
        elif _host_is(root, 'etsy.com') and _ETSY_API_SUFFIX not in root:
            return (None, 'base_url must be the Etsy Open API v3 root (https://openapi.etsy.com/v3/application)')
    return (root, None)

def _etsy_api_key():
    return None

def _etsy_auth(form=False, require_oauth=True):
    headers = {'Accept': 'application/json'}
    if form:
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8'
    api_key = _etsy_api_key()
    if not api_key:
        return (None, 'auth_info.api_key is required')
    headers['x-api-key'] = str(api_key)
    if require_oauth:
        return (None, 'auth_info.access_token is required for this endpoint')
    return (headers, None)

def _etsy_shop_id(shop_id):
    sid = shop_id or (None or {}).get('shop_id')
    if sid in (None, ''):
        return (None, 'shop_id is required (or auth_info.shop_id)')
    return (str(sid).strip(), None)

def _etsy_results(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        results = data.get('results')
        if isinstance(results, list):
            return results
        for key in ('listing_id', 'receipt_id', 'user_id'):
            if data.get(key) is not None:
                return [data]
    return []

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
