from typing import Any, Dict, List, Optional
_SP_API_ROOT = 'https://api.payroll.simplepay.cloud/v1'

async def simplepay_create_customer(client_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """SimplePay: create employee (customer). Official: https://www.simplepay.co.za/api-docs/"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _sp_provision({}, 400, 'payload is required')
        (root, err) = _sp_root(base_url)
        if err:
            return _sp_provision({}, 400, err)
        (cid, err) = _sp_client_id(client_id)
        if err:
            return _sp_provision({}, 400, err)
        (headers, aerr) = _sp_auth(json_body=True)
        if aerr:
            return _sp_provision({}, 401, aerr)
        body = payload if 'employee' in payload else {'employee': payload}
        resp = await nexus_call('POST', f'{root}/clients/{cid}/employees', headers=headers, json=body)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _sp_provision(data if isinstance(data, dict) else {}, resp['status_code'], _sp_err(resp))
        recs = _sp_unwrap_items(data if isinstance(data, dict) else [data], 'employee')
        obj = recs[0] if recs else data if isinstance(data, dict) else {}
        return _sp_provision(obj, resp['status_code'], 'ok', fallback_id=obj.get('id') if isinstance(obj, dict) else None)
    except Exception as e:
        return _sp_provision({}, 500, str(e))

def _sp_root(base_url: str):
    root = (base_url or _SP_API_ROOT).rstrip('/')
    if not root.endswith('/v1'):
        if 'simplepay' not in root:
            return (None, 'base_url must be SimplePay API root (https://api.payroll.simplepay.cloud/v1)')
        root = root + '/v1' if not root.endswith('/v1') else root
    return (root, None)

def _sp_client_id(client_id: Optional[str]):
    cid = client_id or None or None
    if cid in (None, ''):
        return (None, 'client_id is required (or auth_info.client_id)')
    return (str(cid), None)

def _sp_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _sp_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or obj.get('payslip_id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _sp_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _sp_unwrap_items(data, key):
    items = []
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and isinstance(row.get(key), dict):
                items.append(row[key])
            elif isinstance(row, dict):
                items.append(row)
    elif isinstance(data, dict):
        nested = data.get(key)
        if isinstance(nested, dict):
            items = [nested]
        elif isinstance(nested, list):
            items = [x for x in nested if isinstance(x, dict)]
    return items
