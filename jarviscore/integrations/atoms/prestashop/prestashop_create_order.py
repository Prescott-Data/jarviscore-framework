from typing import Any, Dict, List, Optional

async def prestashop_create_order(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create an order (XML body). Official: https://devdocs.prestashop-project.org/9/webservice/getting-started/"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _ps_provision({}, 400, 'payload is required', 'orders')
        (root, err) = _ps_root(base_url)
        if err:
            return _ps_provision({}, 400, err, 'orders')
        xml_body = _ps_build_xml('orders', payload)
        (resp, body, status, msg) = await _ps_request('post', root + '/orders', xml_body=xml_body, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _ps_provision(body if isinstance(body, dict) else {}, status, msg, 'orders')
        return _ps_provision(body if isinstance(body, dict) else {}, status, 'ok', 'orders')
    except Exception as e:
        return _ps_provision({}, 500, str(e), 'orders')

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

def _ps_provision(data, status, msg, resource, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    rid = _ps_extract_id(obj, resource) or fallback_id
    ids = [rid] if rid not in (None, '') else []
    rec = _ps_rows(obj, resource)[0] if _ps_rows(obj, resource) else obj if obj else {'id': rid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

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

def _ps_extract_id(body, resource):
    rows = _ps_rows(body, resource)
    if rows and rows[0].get('id') not in (None, ''):
        return rows[0].get('id')
    singular = _ps_singular(resource)
    obj = body.get(singular) if isinstance(body, dict) else None
    if isinstance(obj, dict) and obj.get('id') not in (None, ''):
        return obj.get('id')
    return None

def _ps_build_xml(resource, payload, resource_id=None):
    singular = _ps_singular(resource)
    payload = payload if isinstance(payload, dict) else {}
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">', f'  <{singular}>']
    rid = resource_id if resource_id not in (None, '') else payload.get('id')
    if rid not in (None, ''):
        lines.append(f'    <id><![CDATA[{rid}]]></id>')
    for (key, val) in payload.items():
        if key == 'id' or val is None:
            continue
        if isinstance(val, (dict, list)):
            continue
        lines.append(f'    <{key}><![CDATA[{val}]]></{key}>')
    lines.append(f'  </{singular}>')
    lines.append('</prestashop>')
    return '\n'.join(lines)

async def _ps_request(method, url, params=None, xml_body=None, timeout=30, verify_ssl=True):
    (headers, err) = _ps_auth(xml_body=xml_body is not None)
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
