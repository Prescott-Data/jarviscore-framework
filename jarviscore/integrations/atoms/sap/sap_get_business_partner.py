async def sap_get_business_partner(account_id: str, partner_id: str) -> dict:
    """Get business partner via the sap API."""
    _base = f'https://{account_id}.s4hana.ondemand.com'
    _h = {'Content-Type': 'application/json'}

    async def _get(p, params=None, headers=None):
        _r = await nexus_call('GET', f'{_base}{p}', headers={**_h, **(headers or {})}, params=params or {})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _post(p, data=None, headers=None):
        _r = await nexus_call('POST', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _put(p, data=None, headers=None):
        _r = await nexus_call('PUT', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _patch(p, data=None, headers=None):
        _r = await nexus_call('PATCH', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}

    async def _delete(p, headers=None):
        _r = await nexus_call('DELETE', f'{_base}{p}', headers={**_h, **(headers or {})})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}
    resp = await _get(f"/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner('{partner_id}')", params={'$format': 'json'}, headers={'Accept': 'application/json'})
    p = resp.get('d', {})
    return {'id': p.get('BusinessPartner'), 'name': p.get('BusinessPartnerFullName'), 'first_name': p.get('FirstName'), 'last_name': p.get('LastName'), 'category': p.get('BusinessPartnerCategory'), 'type': p.get('BusinessPartnerType'), 'group': p.get('BusinessPartnerGrouping'), 'language': p.get('Language'), 'created_at': p.get('CreationDate'), 'changed_at': p.get('LastChangeDate')}
