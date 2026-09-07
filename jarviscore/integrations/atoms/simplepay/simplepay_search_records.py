from typing import Any, Dict, List, Optional
_SP_API_ROOT = 'https://api.payroll.simplepay.cloud/v1'

async def simplepay_search_records(client_id: str, query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """SimplePay: search employees and payslips. Official: https://www.simplepay.co.za/api-docs/"""
    try:
        if not query:
            return _sp_dataset([], 400, 'query is required')
        root, err = _sp_root(base_url)
        if err:
            return _sp_dataset([], 400, err)
        cid, err = _sp_client_id(client_id)
        if err:
            return _sp_dataset([], 400, err)
        headers, aerr = _sp_auth()
        if aerr:
            return _sp_dataset([], 401, aerr)
        cap = _sp_cap(limit)
        records = []
        resp = await nexus_call('GET', f'{root}/clients/{cid}/employees', headers=headers)
        if resp['status_code'] == 401:
            return _sp_dataset([], 401, _sp_err(resp))
        if resp['status_code'] < 400:
            for emp in _sp_unwrap_items(resp['json'] if resp['content'] else [], 'employee'):
                if _sp_match(emp, query):
                    records.append(emp)
                    if len(records) >= cap:
                        return _sp_dataset(records[:cap], 200, 'ok')
                eid = emp.get('id')
                if eid in (None, ''):
                    continue
                presp = await nexus_call('GET', f'{root}/employees/{eid}/payslips', headers=headers)
                if presp['status_code'] >= 400:
                    continue
                for ps in _sp_unwrap_items(presp['json'] if presp['content'] else [], 'payslip'):
                    if _sp_match(ps, query):
                        records.append(ps)
                        if len(records) >= cap:
                            return _sp_dataset(records[:cap], 200, 'ok')
        return _sp_dataset(records[:cap], 200, 'ok')
    except Exception as e:
        return _sp_dataset([], 500, str(e))

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

def _sp_cap(limit):
    return min(max(int(limit or 25), 1), 500)

def _sp_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _sp_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]

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

def _sp_match(record, query):
    q = str(query).lower()
    for key in ('id', 'number', 'first_name', 'last_name', 'email', 'name', 'date'):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
