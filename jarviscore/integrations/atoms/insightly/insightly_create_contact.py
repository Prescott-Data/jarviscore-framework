from typing import Any, Dict, List, Optional
INSIGHTLY_API = 'https://api.na1.insightly.com/v3.1'

async def insightly_create_contact(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create Insightly contact. Official: https://api.na1.insightly.com/v3.1/Help"""
    try:
        if not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required'}
        (api, err) = _in_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, basic, auth_err) = _in_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        resp = await _in_post(f'{api}/Contacts', headers, basic, payload, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = _in_single(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok', 'provision_ids': _in_provision_id(data)}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _in_api_root(base_url):
    root = (base_url or INSIGHTLY_API).rstrip('/')
    if '/v3.1' not in root:
        if _host_is(root, 'insightly.com'):
            root = root + '/v3.1' if not root.endswith('/v3') else root + '.1'
        else:
            return (None, 'base_url must be https://api.{pod}.insightly.com/v3.1')
    return (root, None)

def _in_auth():
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    return (headers, None, None)

async def _in_post(url, headers, basic, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)

def _in_single(data):
    if isinstance(data, dict) and data.get('RECORD_ID') is not None:
        return [data]
    if isinstance(data, dict) and data.get('CONTACT_ID') is not None:
        return [data]
    if isinstance(data, dict) and data.get('ORGANISATION_ID') is not None:
        return [data]
    if isinstance(data, dict) and data.get('OPPORTUNITY_ID') is not None:
        return [data]
    return []

def _in_provision_id(data):
    if not isinstance(data, dict):
        return []
    for key in ('CONTACT_ID', 'ORGANISATION_ID', 'OPPORTUNITY_ID', 'RECORD_ID'):
        if data.get(key) not in (None, ''):
            return [data[key]]
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
