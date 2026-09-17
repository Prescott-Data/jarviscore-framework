async def github_list_repos(visibility: str='all', max_results: int=30) -> list:
    """List repos via the github API."""
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
    resp = await _get('/user/repos', params={'visibility': visibility, 'sort': 'updated', 'per_page': max_results}, headers={'Accept': 'application/vnd.github+json'})
    return [{'id': repo['id'], 'name': repo['name'], 'full_name': repo['full_name'], 'description': repo.get('description'), 'private': repo['private'], 'url': repo['html_url'], 'default_branch': repo['default_branch'], 'updated_at': repo['updated_at'], 'language': repo.get('language'), 'stars': repo['stargazers_count'], 'forks': repo['forks_count']} for repo in resp]
