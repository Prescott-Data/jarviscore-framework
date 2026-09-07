from typing import Any, Dict, List, Optional

async def prestashop_list_orders(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List orders via PrestaShop webservice. Official: https://devdocs.prestashop-project.org/9/webservice/getting-started/"""
    try:
        records, status, msg = await _ps_list('orders', base_url, limit, timeout, verify_ssl)
        return _ps_dataset(records, status, msg)
    except Exception as e:
        return _ps_dataset([], 500, str(e))

def _ps_root(base_url):
    root = (base_url or None or None or None or '').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required (https://shop.example.com/api)')
    if root.endswith('/api'):
        pass
    elif '/api/' in root:
        root = root.split('/api/')[0] + '/api'
    else:
        root = root + '/api'
    return (root, None)

def _ps_auth(xml_body=False):
    import base64
    headers = {'Output-Format': 'JSON', 'Accept': 'application/json'}
    if xml_body:
        headers['Content-Type'] = 'application/xml'
    return (headers, None)

def _ps_cap(limit):
    return min(max(int(limit or 25), 1), 500)

def _ps_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ps_err(resp, body=None):
    if isinstance(body, dict):
        for key in ('errors', 'error', 'message'):
            val = body.get(key)
            if val:
                return str(val)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _ps_singular(resource):
    mapping = {'categories': 'category', 'addresses': 'address'}
    if resource in mapping:
        return mapping[resource]
    if resource.endswith('ies'):
        return resource[:-3] + 'y'
    if resource.endswith('s'):
        return resource[:-1]
    return resource

def _ps_rows(body, resource):
    if not isinstance(body, dict):
        return []
    singular = _ps_singular(resource)
    block = body.get(resource)
    if block is None and isinstance(body.get('prestashop'), dict):
        block = body['prestashop'].get(resource)
    if block is None and singular in body:
        item = body.get(singular)
        return [item] if isinstance(item, dict) else []
    if isinstance(block, list):
        return [x for x in block if isinstance(x, dict)]
    if isinstance(block, dict):
        inner = block.get(singular)
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if isinstance(inner, dict):
            return [inner]
        if block.get('id') is not None:
            return [block]
    return []

async def _ps_request(method, url, params=None, xml_body=None, timeout=30, verify_ssl=True):
    headers, err = _ps_auth(xml_body=xml_body is not None)
    if err:
        return (None, None, 401, err)
    kwargs = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if method == 'get':
        resp = await nexus_call('GET', url, params=params)
    elif method == 'post':
        resp = await nexus_call('POST', url, params=params, data=xml_body)
    elif method == 'put':
        resp = await nexus_call('PUT', url, params=params, data=xml_body)
    elif method == 'patch':
        resp = await nexus_call('PATCH', url, params=params, data=xml_body)
    else:
        return (None, None, 400, f'unsupported method {method}')
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _ps_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')

async def _ps_list(resource, base_url, limit, timeout, verify_ssl, extra_params=None):
    root, err = _ps_root(base_url)
    if err:
        return ([], 400, err)
    cap = _ps_cap(limit)
    records = []
    offset = 0
    page_size = min(cap, 100)
    status = 200
    msg = 'ok'
    while len(records) < cap:
        params = {'display': 'full', 'limit': f'{offset},{page_size}'}
        if extra_params:
            params.update(extra_params)
        resp, body, status, msg = await _ps_request('get', root + '/' + resource, params=params, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return (records, status, msg)
        batch = _ps_rows(body, resource)
        if not batch:
            break
        records.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return (records[:cap], status, msg)
