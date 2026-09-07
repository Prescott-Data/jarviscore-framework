from typing import Any, Dict, List, Optional
_ATTIO_HOST = 'https://api.attio.com'
_OBJECT_SLUGS = {'contacts': 'people', 'contact': 'people', 'people': 'people', 'accounts': 'companies', 'account': 'companies', 'companies': 'companies', 'deals': 'deals', 'deal': 'deals'}

async def attio_list_deals(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Query deal records (POST /v2/objects/deals/records/query). Official: https://docs.attio.com/rest-api/endpoint-reference/records/query-records"""
    try:
        if not base_url:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'base_url is required'}
        api_root, root_err = _attio_api_root(base_url)
        if root_err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': root_err}
        auth_err = _attio_auth_err()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        headers = _attio_headers(json_body=True)
        records, status, message = await _attio_query_records(api_root, 'deals', headers, limit, timeout, verify_ssl)
        if message != 'ok':
            return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
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

def _attio_records(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        batch = data.get('data')
        if isinstance(batch, list):
            return batch
        if batch is not None:
            return [batch]
    return []

async def _attio_query_records(api_root, object_slug, headers, limit, timeout, verify_ssl, extra_body=None):
    records: List[Dict[str, Any]] = []
    offset = 0
    status = 0
    page_size = min(max(limit, 1), 500)
    extra_body = dict(extra_body or {})
    while len(records) < limit:
        body = {'limit': min(page_size, limit - len(records)), 'offset': offset}
        body.update(extra_body)
        resp = await nexus_call('POST', f'{api_root}/objects/{object_slug}/records/query', headers=headers, json=body)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        batch = _attio_records(resp['json'])
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        if len(batch) < body['limit']:
            break
        offset += len(batch)
        if offset > 100000:
            break
    return (records[:limit], status, 'ok')

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
