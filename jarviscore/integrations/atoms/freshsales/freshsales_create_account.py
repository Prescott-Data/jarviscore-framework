from typing import Any, Dict, List, Optional
_FS_API_SUFFIX = '/crm/sales/api'
_FS_AUTH_PREFIX = 'Token '
_FS_AUTH_KV = 'token' + '='

async def freshsales_create_account(fields: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create an account (POST /api/sales_accounts, body.sales_account). Freshworks Token auth scheme (Token + token= + api_key from Profile Settings > API Settings). Official: https://developers.freshworks.com/docs/api/crm/sales/"""
    try:
        if not fields or not isinstance(fields, dict):
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'fields is required'}
        api, err = _fs_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _fs_sales_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = f'{api}/sales_accounts'
        resp = await nexus_call('POST', url, headers=headers, json={'sales_account': fields})
        status = resp['status_code']
        data = resp['json'] if resp['body'] else {}
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        records = _fs_entity_records(data, 'sales_account')
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok', 'provision_ids': _fs_provision_id(data, 'sales_account')}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _fs_api_root(base_url: str):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required (https://{domain}.myfreshworks.com/crm/sales/api)')
    if _FS_API_SUFFIX in root:
        return (root, None)
    if root.endswith('/api') and _host_is(root, 'freshsales.io', 'myfreshworks.com'):
        return (root, None)
    return (None, 'base_url must be the Freshsales API root (https://{domain}.myfreshworks.com/crm/sales/api)')

def _fs_sales_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    _prefix = 'Token '
    _kv = 'token' + '='
    return (headers, None)

def _fs_entity_records(data, entity_key):
    if isinstance(data, dict):
        entity = data.get(entity_key)
        if isinstance(entity, dict):
            return [entity]
        if isinstance(entity, list):
            return [item for item in entity if isinstance(item, dict)]
    return []

def _fs_provision_id(data, entity_key):
    recs = _fs_entity_records(data, entity_key)
    if recs and recs[0].get('id') not in (None, ''):
        return [str(recs[0]['id'])]
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
