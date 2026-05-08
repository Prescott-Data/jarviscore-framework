def sap_get_sales_order(auth_info: dict, account_id: str, order_id: str) -> dict:
    import requests
    _base = f"https://{account_id}.s4hana.ondemand.com"
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
    resp = _get(
        f"/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder('{order_id}')",
        params={"$format": "json", "$expand": "to_Item"},
        headers={"Accept": "application/json"}
    )
    o = resp.get("d", {})
    items_raw = o.get("to_Item", {}).get("results", [])
    return {
        "id": o.get("SalesOrder"),
        "type": o.get("SalesOrderType"),
        "customer": o.get("SoldToParty"),
        "ship_to": o.get("ShipToParty"),
        "currency": o.get("TransactionCurrency"),
        "net_amount": o.get("TotalNetAmount"),
        "date": o.get("SalesOrderDate"),
        "delivery_date": o.get("RequestedDeliveryDate"),
        "status": o.get("OverallSDProcessStatus"),
        "items": [
            {
                "item_number": i.get("SalesOrderItem"),
                "material": i.get("Material"),
                "description": i.get("SalesOrderItemText"),
                "quantity": i.get("RequestedQuantity"),
                "unit": i.get("RequestedQuantityUnit"),
                "net_amount": i.get("NetAmount")
            }
            for i in items_raw
        ]
    }
