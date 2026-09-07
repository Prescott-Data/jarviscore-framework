from typing import Any, Dict, List, Optional
XERO_API = 'https://api.xero.com/api.xro/2.0'

async def xero_get_invoice(invoice_id: str, tenant_id: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """xero REST: get invoice. Official: https://developer.xero.com/documentation/api/accounting/overview"""
    try:
        if not invoice_id:
            return _x_dataset([], 400, 'invoice_id is required')
        root, err = _x_root(base_url)
        if err:
            return _x_dataset([], 400, err)
        headers, aerr = _x_headers(tenant_id)
        if aerr:
            return _x_dataset([], 401, aerr)
        resp = await nexus_call('GET', f'{root}/Invoices/{invoice_id}', headers=headers)
        if resp['status_code'] >= 400:
            return _x_dataset([], resp['status_code'], _x_err(resp))
        return _x_dataset(_x_records(resp['json'] if resp['content'] else {}, 'Invoices'), resp['status_code'], 'ok')
    except Exception as e:
        return _x_dataset([], 500, str(e))

def _x_root(base_url):
    root = (base_url or None or XERO_API).strip().rstrip('/')
    if 'xero.com' not in root:
        return (None, 'base_url must be https://api.xero.com/api.xro/2.0')
    return (root, None)

def _x_headers(tenant_id, json_body=False):
    tenant = tenant_id or None
    if not tenant:
        return (None, 'tenant_id is required (Xero-tenant-id header; from GET /connections)')
    headers = {'Xero-tenant-id': str(tenant), 'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _x_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _x_records(body, key):
    if isinstance(body, dict):
        val = body.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict):
            return [val]
    return []

def _x_err(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            msg = data.get('Message') or data.get('message')
            elems = data.get('Elements')
            if isinstance(elems, list) and elems:
                ve = elems[0].get('ValidationErrors') if isinstance(elems[0], dict) else None
                if isinstance(ve, list) and ve:
                    return str(ve[0].get('Message') or ve[0])[:1000]
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
