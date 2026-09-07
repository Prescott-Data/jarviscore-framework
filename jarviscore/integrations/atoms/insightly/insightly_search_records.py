from typing import Any, Dict, List, Optional
INSIGHTLY_API = 'https://api.na1.insightly.com/v3.1'

async def insightly_search_records(query: str, field_name: str='EMAIL_ADDRESS', limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search Insightly contacts via Contacts/Search. Official: https://api.na1.insightly.com/v3.1/Help"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        api, err = _in_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, basic, auth_err = _in_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        params = {'field_name': field_name, 'field_value': query, 'top': min(max(limit, 1), 500)}
        resp = await _in_get(f'{api}/Contacts/Search', headers, basic, params, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        batch = resp['json'] if resp['body'] else []
        records = [item for item in (batch if isinstance(batch, list) else [batch]) if isinstance(item, dict)][:limit]
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
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

async def _in_get(url, headers, basic, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

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
