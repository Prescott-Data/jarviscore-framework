from typing import Any, Dict, Optional

async def activecampaign_get_contact(contact_id: str, account: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Retrieve contact via GET /contacts/{id}. Official: https://developers.activecampaign.com/reference/get-contact"""
    try:
        if not contact_id:
            return _ac_v3_dataset([], 400, 'contact_id is required')
        (api_root, err) = _ac_v3_resolve_base(base_url, account)
        if err:
            return _ac_v3_dataset([], 400, err)
        (headers, err) = _ac_v3_headers()
        if err:
            return _ac_v3_dataset([], 401, err)
        resp = await nexus_call('GET', f'{api_root}/contacts/{contact_id}', headers=headers)
        status = resp['status_code']
        if status >= 400:
            return _ac_v3_dataset([], status, _ac_v3_err(resp))
        try:
            data = resp['json']
        except Exception:
            return _ac_v3_dataset([], status, 'invalid JSON response')
        if not isinstance(data, dict):
            return _ac_v3_dataset([], status, 'unexpected response format')
        obj = data.get('contact')
        if not isinstance(obj, dict):
            return _ac_v3_dataset([], status, 'missing contact object in response')
        return _ac_v3_dataset([obj], status, 'ok')
    except Exception as e:
        return _ac_v3_dataset([], 500, str(e))

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

def _ac_v3_headers():
    return ({'Accept': 'application/json'}, None)

def _ac_v3_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ac_v3_err(resp):
    return (resp['body'] if resp is not None else 'request failed')[:1000]
