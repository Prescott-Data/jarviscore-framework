from typing import Any, Dict, List, Optional
LACRM_API = 'https://api.lessannoyingcrm.com/v2'

async def less_annoying_crm_get_contact(contact_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get contact via GetContact. Official: https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Contacts"""
    try:
        if not contact_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'contact_id is required'}
        (base, err) = _lacrm_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, aerr) = _lacrm_auth()
        if aerr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': aerr}
        resp = await _lacrm_call(base, headers, 'GetContact', {'ContactId': str(contact_id)}, timeout, verify_ssl)
        data = _lacrm_data(resp)
        errm = _lacrm_err(resp, data)
        if errm:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': errm}
        records = _lacrm_single_contact(data)
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _lacrm_root(base_url):
    root = (base_url or LACRM_API).rstrip('/')
    if not root.endswith('/v2'):
        if _host_is(root, 'lessannoyingcrm.com'):
            root = root + '/v2' if not root.endswith('/v2') else root
        else:
            return (None, 'base_url must be https://api.lessannoyingcrm.com/v2')
    return (root + '/', None)

def _lacrm_auth():
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    return (headers, None)

async def _lacrm_call(base, headers, function, parameters, timeout, verify_ssl):
    body = {'Function': function, 'Parameters': parameters or {}}
    return await nexus_call('POST', base, headers=headers, json=body)

def _lacrm_data(resp):
    try:
        return resp['json'] if resp['body'] else {}
    except Exception:
        return {}

def _lacrm_err(resp, data):
    if resp['status_code'] >= 400:
        if isinstance(data, dict):
            msg = data.get('ErrorDescription') or data.get('Error') or data.get('message')
            if msg:
                return str(msg)
        return resp['body'][:1000]
    if isinstance(data, dict) and data.get('ErrorDescription'):
        return str(data['ErrorDescription'])
    return None

def _lacrm_single_contact(data):
    if isinstance(data, dict) and data.get('ContactId'):
        return [data]
    contact = data.get('Contact') if isinstance(data, dict) else None
    if isinstance(contact, dict):
        return [contact]
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
