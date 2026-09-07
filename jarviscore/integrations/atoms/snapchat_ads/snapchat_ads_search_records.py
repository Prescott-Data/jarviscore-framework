from typing import Any, Dict, List, Optional
_SC_API_ROOT = 'https://adsapi.snapchat.com/v1'

async def snapchat_ads_search_records(ad_account_id: str, query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Snapchat Marketing API: search campaigns and ads. Official: https://marketingapi.snapchat.com/docs/"""
    try:
        if not query:
            return _sc_dataset([], 400, 'query is required')
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
        records = []
        for path in (f'/adaccounts/{aid}/campaigns', f'/adaccounts/{aid}/ads'):
            resp = await nexus_call('GET', root + path, headers=headers, params={'limit': cap})
            if resp['status_code'] == 401:
                return _sc_dataset([], 401, _sc_err(resp))
            if resp['status_code'] >= 400:
                continue
            data = resp['json'] if resp['content'] else {}
            key = 'campaigns' if 'campaigns' in path else 'ads'
            for item in _sc_extract_list(data, key):
                if _sc_match(item, query):
                    records.append(item)
                    if len(records) >= cap:
                        return _sc_dataset(records[:cap], 200, 'ok')
        return _sc_dataset(records[:cap], 200, 'ok')
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

def _sc_match(record, query):
    q = str(query).lower()
    for key in ('id', 'name', 'status'):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
