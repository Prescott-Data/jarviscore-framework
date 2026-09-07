from typing import Any, Dict, List, Optional

async def okta_get_group(domain: str, group_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Retrieve group by id. Official: https://developer.okta.com/docs/reference/api/overview/"""
    try:
        if not group_id:
            return _ok_dataset([], 400, 'group_id is required')
        (root, err) = _ok_root(base_url, domain)
        if err:
            return _ok_dataset([], 400, err)
        (headers, aerr) = _ok_auth()
        if aerr:
            return _ok_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/groups/{group_id}', headers=headers)
        status = resp['status_code']
        if status >= 400:
            return _ok_dataset([], status, _ok_error(resp))
        try:
            data = resp['json']
        except Exception:
            return _ok_dataset([], status, resp['body'][:1000])
        return _ok_dataset(_ok_records(data), status, 'ok')
    except Exception as e:
        return _ok_dataset([], 500, str(e))

def _ok_root(base_url, domain):
    root = (base_url or None or '').strip().rstrip('/')
    dom = (domain or None or None or '').strip()
    if dom:
        dom = dom.replace('https://', '').replace('http://', '').rstrip('/')
    if not root and dom:
        root = f'https://{dom}/api/v1'
    if root and '/api/v1' not in root:
        if 'okta' in root.lower():
            root = root + '/api/v1'
    if not root:
        return (None, 'base_url or domain is required (https://{yourOktaDomain}/api/v1)')
    return (root, None)

def _ok_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _ok_error(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('errorSummary') or data.get('errorCode') or data.get('message')
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _ok_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ok_records(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and data.get('id'):
        return [data]
    return []
