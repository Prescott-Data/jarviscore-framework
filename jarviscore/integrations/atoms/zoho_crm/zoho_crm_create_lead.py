from typing import Any, Dict, List, Optional

async def zoho_crm_create_lead(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """zoho_crm REST: create lead. Official: https://www.zoho.com/crm/developer/docs/api/v2/"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _provision({}, 400, 'payload is required (Last_Name is mandatory for Zoho CRM Leads)')
        root, err = _root(base_url)
        if err:
            return _provision({}, 400, err)
        headers, aerr = _auth(json_body=True)
        if aerr:
            return _provision({}, 401, aerr)
        resp = await nexus_call('POST', root + '/Leads', headers=headers, json={'data': [payload]})
        data = resp['json'] if resp['content'] else {}
        if resp['status_code'] >= 400:
            return _provision({}, resp['status_code'], _err(resp))
        return _provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok')
    except Exception as e:
        return _provision({}, 500, str(e))

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

def _provision(data, status, msg, fallback_id=None):
    rec = {}
    pid = fallback_id
    if isinstance(data, dict):
        rows = data.get('data')
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            row = rows[0]
            details = row.get('details') if isinstance(row.get('details'), dict) else {}
            pid = (details.get('id') if isinstance(details, dict) else None) or row.get('id') or fallback_id
            rec = details or row
    ids = [pid] if pid not in (None, '') else []
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}
