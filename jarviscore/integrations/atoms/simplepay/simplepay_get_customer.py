from typing import Any, Dict, List, Optional
_SP_API_ROOT = 'https://api.payroll.simplepay.cloud/v1'

async def simplepay_get_customer(customer_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """SimplePay: get employee (customer) by ID. Official: https://www.simplepay.co.za/api-docs/"""
    try:
        (root, err) = _sp_root(base_url)
        if err:
            return _sp_dataset([], 400, err)
        if not customer_id:
            return _sp_dataset([], 400, 'customer_id is required')
        (headers, aerr) = _sp_auth()
        if aerr:
            return _sp_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/employees/{customer_id}', headers=headers)
        if resp['status_code'] >= 400:
            return _sp_dataset([], resp['status_code'], _sp_err(resp))
        data = resp['json'] if resp['content'] else {}
        records = _sp_unwrap_items(data if isinstance(data, dict) else [data], 'employee')
        if not records and isinstance(data, dict) and data.get('id'):
            records = [data]
        return _sp_dataset(records[:1], resp['status_code'], 'ok')
    except Exception as e:
        return _sp_dataset([], 500, str(e))

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

def _sp_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

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
