from typing import Any, Dict, List, Optional

async def activecampaign_create_deal(payload: Dict[str, Any], account: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create deal via POST /deals with deal wrapper. Official: https://developers.activecampaign.com/reference/create-a-deal-new"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _ac_v3_provision([], 400, 'payload must be a non-empty dict')
        (api_root, err) = _ac_v3_resolve_base(base_url, account)
        if err:
            return _ac_v3_provision([], 400, err)
        (headers, err) = _ac_v3_headers(json_body=True)
        if err:
            return _ac_v3_provision([], 401, err)
        body = _ac_v3_wrap_resource('deal', payload)
        resp = await nexus_call('POST', f'{api_root}/deals', headers=headers, json=body)
        status = resp['status_code']
        if status >= 400:
            return _ac_v3_provision([], status, _ac_v3_err(resp))
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            return _ac_v3_provision([], status, 'invalid JSON response')
        obj = data.get('deal') if isinstance(data, dict) else None
        records: List[Dict[str, Any]] = [obj] if isinstance(obj, dict) else []
        return _ac_v3_provision(records, status, 'ok', _ac_v3_provision_ids(data, 'deal'))
    except Exception as e:
        return _ac_v3_provision([], 500, str(e))

def _ac_v3_resolve_base(base_url, account):
    if base_url:
        root = str(base_url).strip().rstrip('/')
    elif True .get('api_base'):
        root = str(None).strip().rstrip('/')
    elif account:
        region = None or None or 'us1'
        root = f'https://{account}.api-{region}.com/api/3'
    else:
        return (None, 'base_url or account is required')
    if not root.endswith('/api/3'):
        return (None, 'base_url must be the v3 root ending in /api/3')
    return (root, None)

def _ac_v3_headers(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ac_v3_wrap_resource(resource_key, payload):
    if isinstance(payload, dict) and resource_key in payload:
        return payload
    return {resource_key: payload}

def _ac_v3_provision_ids(data, resource_key):
    if not isinstance(data, dict):
        return []
    obj = data.get(resource_key)
    if isinstance(obj, dict) and obj.get('id') not in (None, ''):
        return [str(obj['id'])]
    if data.get('id') not in (None, ''):
        return [str(data['id'])]
    return []

def _ac_v3_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg, 'provision_ids': ids}

def _ac_v3_err(resp):
    return (resp['body'] if resp is not None else 'request failed')[:1000]
