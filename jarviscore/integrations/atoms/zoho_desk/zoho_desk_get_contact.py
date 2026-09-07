from typing import Any, Dict, List, Optional
ZD_API = 'https://desk.zoho.com/api/v1'

async def zoho_desk_get_contact(contact_id: str, org_id: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """zoho_desk API: get contact. Official: https://desk.zoho.com/DeskAPIDocument"""
    try:
        if not contact_id:
            return _zd_dataset([], 400, 'contact_id is required')
        (root, err) = _zd_root(base_url)
        if err:
            return _zd_dataset([], 400, err)
        (headers, aerr) = _zd_headers(org_id)
        if aerr:
            return _zd_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/contacts/{contact_id}', headers=headers)
        if resp['status_code'] >= 400:
            return _zd_dataset([], resp['status_code'], _zd_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _zd_dataset([data] if isinstance(data, dict) and data else [], resp['status_code'], 'ok')
    except Exception as e:
        return _zd_dataset([], 500, str(e))

def _zd_root(base_url):
    root = (base_url or None or ZD_API).strip().rstrip('/')
    if 'zoho.' not in root:
        return (None, 'base_url must be https://desk.zoho.com/api/v1')
    return (root, None)

def _zd_headers(org_id=''):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if org_id:
        headers['orgId'] = str(org_id)
    return (headers, None)

def _zd_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _zd_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
