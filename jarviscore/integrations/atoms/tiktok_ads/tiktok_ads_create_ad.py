from typing import Any, Dict, List, Optional
_TT_ROOT = 'https://business-api.tiktok.com/open_api/v1.3'

async def tiktok_ads_create_ad(adgroup_id: str, ad_name: str, advertiser_id: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """TikTok Marketing API: Create ad. Official: https://business-api.tiktok.com/portal/docs"""
    try:
        (root, err) = _tt_root(base_url)
        if err:
            return _tt_provision({}, 400, err)
        if not adgroup_id or not ad_name:
            return _tt_provision({}, 400, 'adgroup_id and ad_name are required')
        (aid, err) = _tt_advertiser(advertiser_id)
        if err:
            return _tt_provision({}, 400, err)
        (headers, aerr) = _tt_auth()
        if aerr:
            return _tt_provision({}, 401, aerr)
        headers['Content-Type'] = 'application/json'
        body = {'advertiser_id': aid, 'adgroup_id': adgroup_id, 'ad_name': ad_name}
        resp = await nexus_call('POST', root + '/ad/create/', headers=headers, json=body)
        data = resp['json'] if resp['content'] else {}
        if resp['status_code'] >= 400:
            return _tt_provision({}, resp['status_code'], _tt_err(resp, data))
        return _tt_provision(data, resp['status_code'], 'ok')
    except Exception as e:
        return _tt_provision({}, 500, str(e))

def _tt_root(base_url):
    root = (base_url or None or _TT_ROOT).strip().rstrip('/')
    return (root, None)

def _tt_auth():
    return ({'Accept': 'application/json'}, None)

def _tt_advertiser(advertiser_id):
    aid = advertiser_id or None or None
    if not aid:
        return (None, 'advertiser_id is required (or auth_info.advertiser_id)')
    return (str(aid), None)

def _tt_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get('data') if isinstance(obj.get('data'), dict) else obj
    pid = (inner or {}).get('campaign_id') or (inner or {}).get('ad_id') or (inner or {}).get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = inner if inner else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _tt_err(resp, data=None):
    if isinstance(data, dict):
        return str(data.get('message') or data)[:1000]
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
