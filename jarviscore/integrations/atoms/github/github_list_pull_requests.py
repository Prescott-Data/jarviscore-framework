async def github_list_pull_requests(owner: str, repo: str, state: str='open', max_results: int=30) -> list:
    """List pull requests via the github API."""
    _base = 'https://api.github.com'
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
    items = await _get(f'/repos/{owner}/{repo}/pulls', params={'state': state, 'per_page': max_results, 'sort': 'updated'}, headers={'Accept': 'application/vnd.github+json'})
    return [{'number': pr['number'], 'title': pr['title'], 'state': pr['state'], 'body': pr.get('body'), 'url': pr['html_url'], 'user': pr['user']['login'], 'head': pr['head']['ref'], 'base': pr['base']['ref'], 'draft': pr.get('draft', False), 'created_at': pr['created_at'], 'updated_at': pr['updated_at']} for pr in items]
