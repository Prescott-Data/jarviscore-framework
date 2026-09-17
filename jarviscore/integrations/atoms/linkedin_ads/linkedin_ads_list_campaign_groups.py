async def linkedin_ads_list_campaign_groups(account_id: str, count: int=25, start: int=0) -> list:
    """Ads list campaign groups via the linkedin_ads API."""
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
    account_urn = f'urn:li:sponsoredAccount:{account_id}'
    resp = await _get('/adCampaignGroupsV2', params={'q': 'search', 'search.account.values': f'List({account_urn})', 'count': count, 'start': start})
    return [{'id': g.get('id'), 'name': g.get('name'), 'status': g.get('status'), 'account': g.get('account'), 'run_schedule_start': g.get('runSchedule', {}).get('start'), 'run_schedule_end': g.get('runSchedule', {}).get('end'), 'total_budget': g.get('totalBudget', {}).get('amount')} for g in resp.get('elements', [])]
