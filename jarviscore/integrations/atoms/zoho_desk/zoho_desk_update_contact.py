from typing import Any, Dict, List, Optional
ZD_API = 'https://desk.zoho.com/api/v1'

async def zoho_desk_update_contact(contact_id: str, first_name: str='', last_name: str='', email: str='', org_id: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """zoho_desk API: update contact. Official: https://desk.zoho.com/DeskAPIDocument"""
    try:
        if not contact_id:
            return _zd_provision({}, 400, 'contact_id is required')
        (root, err) = _zd_root(base_url)
        if err:
            return _zd_provision({}, 400, err)
        (headers, aerr) = _zd_headers(org_id)
        if aerr:
            return _zd_provision({}, 401, aerr)
        body: Dict[str, Any] = {}
        if first_name:
            body['firstName'] = first_name
        if last_name:
            body['lastName'] = last_name
        if email:
            body['email'] = email
        resp = await nexus_call('PATCH', f'{root}/contacts/{contact_id}', headers=headers, json=body)
        if resp['status_code'] >= 400:
            return _zd_provision({}, resp['status_code'], _zd_err(resp))
        data = resp['json'] if resp['content'] else {}
        return _zd_provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok', fallback_id=contact_id)
    except Exception as e:
        return _zd_provision({}, 500, str(e))

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

def _zd_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _zd_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
