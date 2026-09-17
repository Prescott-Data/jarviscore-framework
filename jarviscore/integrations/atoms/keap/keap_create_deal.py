from typing import Any, Dict, List, Optional
KEAP_API = 'https://api.infusionsoft.com/crm/rest/v2'

async def keap_create_deal(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create Keap deal. Official: https://developer.keap.com/docs/restv2/"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        (api, err) = _kp_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _kp_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        resp = await _kp_post(f'{api}/opportunities', headers, payload, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _kp_single(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': _kp_provision_id(data)}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _kp_api_root(base_url):
    root = (base_url or KEAP_API).rstrip('/')
    if '/rest/v2' not in root:
        if _host_is(root, 'infusionsoft.com', 'keap.com'):
            root = root + '/crm/rest/v2' if '/crm' not in root else root + '/rest/v2' if not root.endswith('/v2') else root
        else:
            return (None, 'base_url must be https://api.infusionsoft.com/crm/rest/v2')
    return (root, None)

def _kp_auth():
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    return (headers, None)

async def _kp_post(url, headers, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

def _kp_single(data):
    if isinstance(data, dict) and data.get('id') is not None:
        return [data]
    return []

def _kp_provision_id(data):
    recs = _kp_single(data)
    if recs:
        return [recs[0]['id']]
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
