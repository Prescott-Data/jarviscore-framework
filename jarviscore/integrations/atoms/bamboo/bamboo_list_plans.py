async def bamboo_list_plans(cloud_id: str, project_key: str=None, max_results: int=25) -> list:
    """List plans via the bamboo API."""
    _base = f'https://api.atlassian.com/bamboo/{cloud_id}'
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
    params = {'max-result': max_results, 'expand': 'plans.plan'}
    if project_key:
        resp = await _get(f'/rest/api/latest/project/{project_key}', params=params)
        plans = resp.get('plans', {}).get('plan', [])
    else:
        resp = await _get('/rest/api/latest/plan', params=params)
        plans = resp.get('plans', {}).get('plan', [])
    return [{'key': p['key'], 'name': p['name'], 'project_key': p.get('projectKey'), 'enabled': p.get('enabled', True), 'href': p.get('link', {}).get('href')} for p in plans]
