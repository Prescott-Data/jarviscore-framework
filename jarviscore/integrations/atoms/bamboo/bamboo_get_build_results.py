async def bamboo_get_build_results(cloud_id: str, plan_key: str, max_results: int=10) -> list:
    """Get build results via the bamboo API."""
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
    resp = await _get(f'/rest/api/latest/result/{plan_key}', params={'max-result': max_results, 'expand': 'results.result'})
    results = resp.get('results', {}).get('result', [])
    return [{'key': r['key'], 'build_number': r.get('buildNumber'), 'state': r.get('state'), 'build_state': r.get('buildState'), 'life_cycle_state': r.get('lifeCycleState'), 'started_at': r.get('buildStartedTime'), 'completed_at': r.get('buildCompletedTime'), 'duration_seconds': r.get('buildDurationInSeconds'), 'href': r.get('link', {}).get('href')} for r in results]
