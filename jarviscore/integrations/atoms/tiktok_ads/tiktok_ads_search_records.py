from typing import Any, Dict, List, Optional
_TT_ROOT = 'https://business-api.tiktok.com/open_api/v1.3'

async def tiktok_ads_search_records(query: str, advertiser_id: str='', limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """TikTok Marketing API: Search campaigns. Official: https://business-api.tiktok.com/portal/docs"""
    try:
        (root, err) = _tt_root(base_url)
        if err:
            return _tt_dataset([], 400, err)
        if not query:
            return _tt_dataset([], 400, 'query is required')
        (aid, err) = _tt_advertiser(advertiser_id)
        if err:
            return _tt_dataset([], 400, err)
        (headers, aerr) = _tt_auth()
        if aerr:
            return _tt_dataset([], 401, aerr)
        resp = await nexus_call('GET', root + '/campaign/get/', headers=headers, params={'advertiser_id': aid, 'page_size': 100})
        data = resp['json'] if resp['content'] else {}
        if resp['status_code'] >= 400:
            return _tt_dataset([], resp['status_code'], _tt_err(resp, data))
        items = _tt_list(data, 'campaigns')
        q = query.lower()
        matched = [x for x in items if q in str(x.get('campaign_name', '')).lower() or q in str(x.get('campaign_id', '')).lower()]
        return _tt_dataset(matched[:limit], resp['status_code'], 'ok')
    except Exception as e:
        return _tt_dataset([], 500, str(e))

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

def _tt_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tt_err(resp, data=None):
    if isinstance(data, dict):
        return str(data.get('message') or data)[:1000]
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _tt_list(data, key):
    if not isinstance(data, dict):
        return []
    inner = data.get('data') or {}
    if isinstance(inner, dict):
        items = inner.get('list') or inner.get(key) or []
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []
