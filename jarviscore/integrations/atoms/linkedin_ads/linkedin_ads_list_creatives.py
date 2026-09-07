async def linkedin_ads_list_creatives(campaign_id: str, count: int=25, start: int=0) -> list:
    """Ads list creatives via the linkedin_ads API."""
    _base = 'https://api.linkedin.com/v2'
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
    campaign_urn = f'urn:li:sponsoredCampaign:{campaign_id}'
    resp = await _get('/adCreativesV2', params={'q': 'search', 'search.campaign.values': f'List({campaign_urn})', 'count': count, 'start': start})
    return [{'id': cr.get('id'), 'status': cr.get('status'), 'type': cr.get('type'), 'campaign': cr.get('campaign'), 'reference': cr.get('reference'), 'variables': cr.get('variables')} for cr in resp.get('elements', [])]
