from typing import Any, Dict, List, Optional
_XA_ROOT = 'https://ads-api.x.com/12'

async def twitter_ads_list_ads(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """X Ads API: list ads. Official: https://developer.x.com/en/docs/twitter-ads-api"""
    try:
        root, err = _xa_root(base_url)
        if err:
            return _xa_dataset([], 400, err)
        headers, aerr = _xa_auth()
        if aerr:
            return _xa_dataset([], 401, aerr)
        aid, err = _xa_account()
        if err:
            return _xa_dataset([], 400, err)
        resp = await nexus_call('GET', f'{root}/accounts/{aid}/promoted_tweets', headers=headers, params={'count': limit})
        if resp['status_code'] >= 400:
            return _xa_dataset([], resp['status_code'], _xa_err(resp))
        return _xa_dataset(_xa_rows(resp['json'] if resp['content'] else {}), resp['status_code'], 'ok')
    except Exception as e:
        return _xa_dataset([], 500, str(e))

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

def _xa_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _xa_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _xa_rows(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        d = data.get('data')
        if isinstance(d, list):
            return [x for x in d if isinstance(x, dict)]
        if isinstance(d, dict):
            return [d]
    return []
