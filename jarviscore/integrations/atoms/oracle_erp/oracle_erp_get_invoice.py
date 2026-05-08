def oracle_erp_get_invoice(auth_info: dict, instance_url: str, invoice_id: str) -> dict:
    import requests
    _base = f"{instance_url.rstrip('/')}/fscmRestApi/resources/latest"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    def _get(p, params=None, headers=None):
        _r = requests.get(f"{_base}{p}", headers={**_h, **(headers or {})}, params=params or {}, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _post(p, data=None, headers=None):
        _r = requests.post(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _put(p, data=None, headers=None):
        _r = requests.put(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _patch(p, data=None, headers=None):
        _r = requests.patch(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json() if _r.content else {}
    def _delete(p, headers=None):
        _r = requests.delete(f"{_base}{p}", headers={**_h, **(headers or {})}, timeout=30)
        _r.raise_for_status()
        return _r.json() if _r.content else {}
    resp = _get(f"/invoices/{invoice_id}")
    return {
        "id": resp.get("InvoiceId"),
        "number": resp.get("InvoiceNumber"),
        "type": resp.get("InvoiceType"),
        "supplier": resp.get("Supplier"),
        "supplier_site": resp.get("SupplierSite"),
        "amount": resp.get("InvoiceAmount"),
        "currency": resp.get("InvoiceCurrencyCode"),
        "date": resp.get("InvoiceDate"),
        "due_date": resp.get("PaymentDueDate"),
        "status": resp.get("InvoiceStatus"),
        "payment_method": resp.get("PaymentMethod"),
        "description": resp.get("Description"),
        "created_by": resp.get("CreatedBy"),
        "created_at": resp.get("CreationDate")
    }
