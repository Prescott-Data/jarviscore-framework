from typing import Any, Dict, List, Optional
_SP_API_ROOT = 'https://api.payroll.simplepay.cloud/v1'

async def simplepay_update_customer(customer_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """SimplePay: update employee (customer). Official: https://www.simplepay.co.za/api-docs/"""
    try:
        if not customer_id:
            return _sp_provision({}, 400, 'customer_id is required')
        if not isinstance(payload, dict) or not payload:
            return _sp_provision({}, 400, 'payload is required')
        root, err = _sp_root(base_url)
        if err:
            return _sp_provision({}, 400, err)
        headers, aerr = _sp_auth(json_body=True)
        if aerr:
            return _sp_provision({}, 401, aerr)
        body = payload if 'employee' in payload else {'employee': payload}
        resp = await nexus_call('PATCH', f'{root}/employees/{customer_id}', headers=headers, json=body)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _sp_provision(data if isinstance(data, dict) else {}, resp['status_code'], _sp_err(resp))
        return _sp_provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok', fallback_id=data.get('id') if isinstance(data, dict) else customer_id)
    except Exception as e:
        return _sp_provision({}, 500, str(e))

def _sp_root(base_url: str):
    root = (base_url or _SP_API_ROOT).rstrip('/')
    if not root.endswith('/v1'):
        if 'simplepay' not in root:
            return (None, 'base_url must be SimplePay API root (https://api.payroll.simplepay.cloud/v1)')
        root = root + '/v1' if not root.endswith('/v1') else root
    return (root, None)

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
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
