from typing import Any, Dict, List, Optional
_ATTIO_HOST = 'https://api.attio.com'
_OBJECT_SLUGS = {'contacts': 'people', 'contact': 'people', 'people': 'people', 'accounts': 'companies', 'account': 'companies', 'companies': 'companies', 'deals': 'deals', 'deal': 'deals'}

async def attio_create_contact(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create person record (POST /v2/objects/people/records). Official: https://docs.attio.com/rest-api/endpoint-reference/records/create-a-record"""
    try:
        if not base_url:
            return _attio_provision([], 400, 'base_url is required')
        api_root, root_err = _attio_api_root(base_url)
        if root_err:
            return _attio_provision([], 400, root_err)
        auth_err = _attio_auth_err()
        if auth_err:
            return _attio_provision([], 401, auth_err)
        headers = _attio_headers(json_body=True)
        resp = await nexus_call('POST', f'{api_root}/objects/people/records', headers=headers, json=_attio_wrap_values(payload))
        status = resp['status_code']
        try:
            body = resp['json'] if resp['content'] else {}
        except Exception:
            body = {}
        if status >= 400:
            return _attio_provision([], status, _attio_err(resp))
        rec = _attio_record(body)
        records = [rec] if rec else []
        return _attio_provision(records, status, 'ok', _attio_provision_ids(body))
    except Exception as e:
        return _attio_provision([], 500, str(e))

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

def _attio_wrap_values(payload):
    if isinstance(payload, dict) and isinstance(payload.get('data'), dict):
        return payload
    if isinstance(payload, dict) and 'values' in payload:
        return {'data': payload}
    return {'data': {'values': payload or {}}}

def _attio_provision_id(body):
    if not isinstance(body, dict):
        return []
    data = body.get('data')
    if isinstance(data, dict):
        rid = data.get('id')
        if isinstance(rid, dict) and rid.get('record_id') not in (None, ''):
            return [rid['record_id']]
        if data.get('record_id') not in (None, ''):
            return [data['record_id']]
    rid = body.get('id')
    if isinstance(rid, dict) and rid.get('record_id') not in (None, ''):
        return [rid['record_id']]
    return []

def _attio_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg, 'provision_ids': ids}

def _attio_provision_ids(body, fallback_id=None):
    ids = _attio_provision_id(body)
    if ids:
        return [str(x) for x in ids]
    if fallback_id not in (None, ''):
        return [str(fallback_id)]
    return []

def _attio_record(body):
    if isinstance(body, dict) and isinstance(body.get('data'), dict):
        return body['data']
    return {}

def _attio_err(resp):
    return (resp['body'] if resp is not None else 'request failed')[:1000]

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
