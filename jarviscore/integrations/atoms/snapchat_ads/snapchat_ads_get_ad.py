from typing import Any, Dict, List, Optional
_SC_API_ROOT = 'https://adsapi.snapchat.com/v1'

async def snapchat_ads_get_ad(ad_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Snapchat Marketing API: get ad. Official: https://marketingapi.snapchat.com/docs/"""
    try:
        (root, err) = _sc_root(base_url)
        if err:
            return _sc_dataset([], 400, err)
        if not ad_id:
            return _sc_dataset([], 400, 'ad_id is required')
        (headers, aerr) = _sc_auth()
        if aerr:
            return _sc_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/ads/{ad_id}', headers=headers)
        if resp['status_code'] >= 400:
            return _sc_dataset([], resp['status_code'], _sc_err(resp))
        data = resp['json'] if resp['content'] else {}
        records = _sc_extract_list(data, 'ads')
        if not records and isinstance(data.get('ad'), dict):
            records = [data['ad']]
        return _sc_dataset(records[:1], resp['status_code'], 'ok')
    except Exception as e:
        return _sc_dataset([], 500, str(e))

def _sc_root(base_url: str):
    root = (base_url or _SC_API_ROOT).rstrip('/')
    if 'adsapi.snapchat.com' not in root:
        return (None, 'base_url must be Snapchat Ads API root (https://adsapi.snapchat.com/v1)')
    return (root, None)

def _sc_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

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
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

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
