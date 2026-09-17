async def linkedin_ads_get_campaign(campaign_id: str) -> dict:
    """Ads get campaign via the linkedin_ads API."""
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
    c = await _get(f'/adCampaignsV2/{campaign_id}')
    return {'id': c.get('id'), 'name': c.get('name'), 'status': c.get('status'), 'type': c.get('type'), 'objective_type': c.get('objectiveType'), 'cost_type': c.get('costType'), 'daily_budget': c.get('dailyBudget', {}).get('amount'), 'unit_cost': c.get('unitCost', {}).get('amount'), 'targeting_criteria': c.get('targetingCriteria'), 'campaign_group': c.get('campaignGroup'), 'account': c.get('account'), 'run_schedule_start': c.get('runSchedule', {}).get('start'), 'run_schedule_end': c.get('runSchedule', {}).get('end')}
