from typing import Any, Dict, List, Optional
_SC_API_ROOT = 'https://adsapi.snapchat.com/v1'

async def snapchat_ads_update_campaign(ad_account_id: str, campaign_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Snapchat Marketing API: update campaign. Official: https://marketingapi.snapchat.com/docs/"""
    try:
        if not campaign_id:
            return _sc_provision({}, 400, 'campaign_id is required')
        if not isinstance(payload, dict) or not payload:
            return _sc_provision({}, 400, 'payload is required')
        (root, err) = _sc_root(base_url)
        if err:
            return _sc_provision({}, 400, err)
        (aid, err) = _sc_ad_account(ad_account_id)
        if err:
            return _sc_provision({}, 400, err)
        (headers, aerr) = _sc_auth(json_body=True)
        if aerr:
            return _sc_provision({}, 401, aerr)
        camp = dict(payload)
        camp.setdefault('id', campaign_id)
        camp.setdefault('ad_account_id', aid)
        resp = await nexus_call('PUT', f'{root}/adaccounts/{aid}/campaigns', headers=headers, json={'campaigns': [camp]})
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _sc_provision(data if isinstance(data, dict) else {}, resp['status_code'], _sc_err(resp))
        records = _sc_extract_list(data, 'campaigns')
        obj = records[0] if records else data.get('campaign') if isinstance(data, dict) else {}
        if not isinstance(obj, dict):
            obj = {}
        return _sc_provision(obj, resp['status_code'], 'ok', fallback_id=obj.get('id') or campaign_id)
    except Exception as e:
        return _sc_provision({}, 500, str(e))

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

def _sc_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

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
