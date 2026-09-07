from typing import Any, Dict, List, Optional
_ATTIO_HOST = 'https://api.attio.com'
_OBJECT_SLUGS = {'contacts': 'people', 'contact': 'people', 'people': 'people', 'accounts': 'companies', 'account': 'companies', 'companies': 'companies', 'deals': 'deals', 'deal': 'deals'}

async def attio_get_account(account_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get company record (GET /v2/objects/companies/records/{record_id}). Official: https://docs.attio.com/rest-api/endpoint-reference/records/get-a-record"""
    try:
        if not base_url:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'base_url is required'}
        if not account_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'account_id is required'}
        api_root, root_err = _attio_api_root(base_url)
        if root_err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': root_err}
        auth_err = _attio_auth_err()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        headers = _attio_headers()
        resp = await nexus_call('GET', f'{api_root}/objects/companies/records/{account_id}', headers=headers)
        status = resp['status_code']
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        body = resp['json']
        item = body.get('data') if isinstance(body, dict) else body
        records = [item] if isinstance(item, dict) else []
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _attio_api_root(base_url: str):
    root = base_url.rstrip('/')
    if root.endswith('/v2'):
        return (root, None)
    if root.endswith('/v1'):
        root = root[:-len('/v1')]
    if root == _ATTIO_HOST or _host_is(root, 'api.attio.com'):
        return (_ATTIO_HOST + '/v2', None)
    return (None, 'base_url must be https://api.attio.com')

def _attio_headers(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return headers

def _attio_auth_err():
    return None

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
