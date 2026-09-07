from typing import Any, Dict, List, Optional
_GQL = 'https://gql.waveapps.com/graphql/public'

async def wave_accounting_update_contact(business_id: str='', customer_id: str='', invoice_id: str='', payment_id: str='', name: str='', query: str='', limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Wave GraphQL: update contact. Official: https://developer.waveapps.com/hc/en-us/articles/360019588314-API-Reference"""
    try:
        if not customer_id:
            return _wv_provision({}, 400, 'customer_id is required')
        gql = 'mutation PatchCustomer($input: CustomerPatchInput!) { customerPatch(input: $input) { didSucceed inputErrors { message code path } customer { id name email } } }'
        inp = {'id': str(customer_id)}
        if name:
            inp['name'] = name
        email = (None or {}).get('email')
        if email:
            inp['email'] = email
        data, status, err = await _wv_post(gql, base_url, {'input': inp}, timeout, verify_ssl)
        if err:
            return _wv_provision({}, 401, err)
        if status >= 400 or (isinstance(data, dict) and data.get('errors')):
            return _wv_provision({}, status if status >= 400 else 400, str((data or {}).get('errors') or data)[:1000])
        payload = (data.get('data') or {}).get('customerPatch') or {} if isinstance(data, dict) else {}
        if not payload.get('didSucceed'):
            return _wv_provision({}, 400, str(payload.get('inputErrors') or 'customerPatch failed')[:1000])
        return _wv_provision(payload.get('customer') or {}, status, 'ok')
    except Exception as e:
        return _wv_provision({}, 500, str(e))

def _wv_auth():
    return ({'Content-Type': 'application/json'}, None)

def _wv_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

async def _wv_post(query, base_url=None, variables=None, timeout=30, verify_ssl=True):
    headers, err = _wv_auth()
    if err:
        return (None, 401, err)
    resp = await nexus_call('POST', base_url or _GQL, headers=headers, json={'query': query, 'variables': variables or {}})
    try:
        data = resp['json'] if resp['content'] else {}
    except Exception:
        data = {}
    return (data, resp['status_code'], None)
