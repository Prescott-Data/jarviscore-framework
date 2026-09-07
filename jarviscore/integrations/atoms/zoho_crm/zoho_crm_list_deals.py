from typing import Any, Dict, List, Optional

async def zoho_crm_list_deals(limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """zoho_crm REST: list deals. Official: https://www.zoho.com/crm/developer/docs/api/v2/"""
    try:
        (root, err) = _root(base_url)
        if err:
            return _dataset([], 400, err)
        (headers, aerr) = _auth()
        if aerr:
            return _dataset([], 401, aerr)
        resp = await nexus_call('GET', root + '/Deals', headers=headers, params={'per_page': _cap(limit)})
        if resp['status_code'] == 204:
            return _dataset([], 200, 'ok')
        if resp['status_code'] >= 400:
            return _dataset([], resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        return _dataset(_records(data)[:_cap(limit)], resp['status_code'], 'ok')
    except Exception as e:
        return _dataset([], 500, str(e))

def _root(base_url):
    root = (base_url or None or 'https://www.zohoapis.com/crm/v2').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required')
    return (root, None)

def _auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _cap(limit):
    return min(max(int(limit or 25), 1), 200)

def _err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('message') or data.get('code')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or 'HTTP ' + str(resp['status_code']))[:1000]

def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _records(data):
    if isinstance(data, dict):
        rows = data.get('data')
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []
