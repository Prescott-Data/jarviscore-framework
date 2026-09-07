from typing import Any, Dict, List, Optional
_XA_ROOT = 'https://ads-api.x.com/12'

async def twitter_ads_create_campaign(name: str, funding_instrument_id: str, daily_budget_amount_local_micro: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """X Ads API: create campaign. Official: https://developer.x.com/en/docs/twitter-ads-api"""
    try:
        root, err = _xa_root(base_url)
        if err:
            return _xa_provision({}, 400, err)
        if not name or not funding_instrument_id:
            return _xa_provision({}, 400, 'name and funding_instrument_id are required')
        headers, aerr = _xa_auth()
        if aerr:
            return _xa_provision({}, 401, aerr)
        aid, err = _xa_account()
        if err:
            return _xa_provision({}, 400, err)
        params = {'name': name, 'funding_instrument_id': funding_instrument_id, 'daily_budget_amount_local_micro': daily_budget_amount_local_micro or '1000000', 'entity_status': 'ACTIVE'}
        resp = await nexus_call('POST', f'{root}/accounts/{aid}/campaigns', headers=headers, params=params)
        if resp['status_code'] >= 400:
            return _xa_provision({}, resp['status_code'], _xa_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _xa_provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok')
    except Exception as e:
        return _xa_provision({}, 500, str(e))

def _xa_root(base_url):
    root = (base_url or None or _XA_ROOT).strip().rstrip('/')
    return (root, None)

def _xa_auth():
    return ({'Accept': 'application/json'}, None)

def _xa_account():
    aid = None or None
    if not aid:
        return (None, 'auth_info.account_id is required')
    return (str(aid), None)

def _xa_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get('data')
    if isinstance(inner, dict):
        obj = inner
    elif isinstance(inner, list) and inner and isinstance(inner[0], dict):
        obj = inner[0]
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _xa_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
