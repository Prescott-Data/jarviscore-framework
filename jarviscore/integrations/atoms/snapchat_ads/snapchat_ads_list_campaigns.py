from typing import Any, Dict, List, Optional
_SC_API_ROOT = 'https://adsapi.snapchat.com/v1'

async def snapchat_ads_list_campaigns(ad_account_id: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Snapchat Marketing API: list campaigns. Official: https://marketingapi.snapchat.com/docs/"""
    try:
        root, err = _sc_root(base_url)
        if err:
            return _sc_dataset([], 400, err)
        aid, err = _sc_ad_account(ad_account_id)
        if err:
            return _sc_dataset([], 400, err)
        headers, aerr = _sc_auth()
        if aerr:
            return _sc_dataset([], 401, aerr)
        cap = _sc_cap(limit)
        resp = await nexus_call('GET', f'{root}/adaccounts/{aid}/campaigns', headers=headers, params={'limit': cap})
        if resp['status_code'] >= 400:
            return _sc_dataset([], resp['status_code'], _sc_err(resp))
        data = resp['json'] if resp['content'] else {}
        records = _sc_extract_list(data, 'campaigns')[:cap]
        records = await _sc_paging(resp, data, cap, records, 'campaigns')
        return _sc_dataset(records[:cap], resp['status_code'], 'ok')
    except Exception as e:
        return _sc_dataset([], 500, str(e))

def _sc_root(base_url: str):
    root = (base_url or _SC_API_ROOT).rstrip('/')
    if 'adsapi.snapchat.com' not in root:
        return (None, 'base_url must be Snapchat Ads API root (https://adsapi.snapchat.com/v1)')
    return (root, None)

def _sc_ad_account(ad_account_id: Optional[str]):
    aid = ad_account_id or None or None
    if aid in (None, ''):
        return (None, 'ad_account_id is required (or auth_info.ad_account_id)')
    return (str(aid), None)

def _sc_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _sc_cap(limit):
    return min(max(int(limit or 25), 1), 1000)

def _sc_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sc_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            return str(data.get('debug_message') or data.get('display_message') or data)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

def _sc_extract_list(data, resource_key):
    records = []
    if not isinstance(data, dict):
        return records
    rows = data.get(resource_key) or []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get(resource_key[:-1] if resource_key.endswith('s') else resource_key), dict):
                inner_key = resource_key[:-1] if resource_key.endswith('s') else resource_key
                records.append(row[inner_key])
            elif isinstance(row, dict) and resource_key[:-1] in row:
                records.append(row[resource_key[:-1]])
    return records

async def _sc_paging(resp, data, cap, records, resource_key):
    paging = data.get('paging') if isinstance(data, dict) else {}
    next_link = paging.get('next_link') if isinstance(paging, dict) else None
    if next_link and len(records) < cap:
        nresp = await nexus_call('GET', next_link)
        if nresp['status_code'] < 400:
            ndata = nresp['json'] if nresp['content'] else {}
            records.extend(_sc_extract_list(ndata, resource_key)[:cap - len(records)])
    return records
