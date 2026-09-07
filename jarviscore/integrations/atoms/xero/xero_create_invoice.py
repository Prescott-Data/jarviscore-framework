from typing import Any, Dict, List, Optional
XERO_API = 'https://api.xero.com/api.xro/2.0'

async def xero_create_invoice(contact_id: str, line_items: List[Dict[str, Any]], tenant_id: str='', type: str='ACCREC', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """xero REST: create invoice. Official: https://developer.xero.com/documentation/api/accounting/overview"""
    try:
        if not contact_id:
            return _x_provision({}, 'Invoices', 'InvoiceID', 400, 'contact_id is required')
        if not line_items:
            return _x_provision({}, 'Invoices', 'InvoiceID', 400, 'line_items is required')
        (root, err) = _x_root(base_url)
        if err:
            return _x_provision({}, 'Invoices', 'InvoiceID', 400, err)
        (headers, aerr) = _x_headers(tenant_id, json_body=True)
        if aerr:
            return _x_provision({}, 'Invoices', 'InvoiceID', 401, aerr)
        invoice = {'Type': type, 'Contact': {'ContactID': str(contact_id)}, 'LineItems': line_items}
        resp = await nexus_call('PUT', f'{root}/Invoices', headers=headers, json={'Invoices': [invoice]})
        if resp['status_code'] >= 400:
            return _x_provision({}, 'Invoices', 'InvoiceID', resp['status_code'], _x_err(resp))
        return _x_provision(resp['json'] if resp['content'] else {}, 'Invoices', 'InvoiceID', resp['status_code'], 'ok')
    except Exception as e:
        return _x_provision({}, 'Invoices', 'InvoiceID', 500, str(e))

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

def _x_records(body, key):
    if isinstance(body, dict):
        val = body.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict):
            return [val]
    return []

def _x_provision(body, key, id_field, status, msg, fallback_id=None):
    recs = _x_records(body, key)
    obj = recs[0] if recs else {}
    pid = obj.get(id_field) or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {id_field: pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

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
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
