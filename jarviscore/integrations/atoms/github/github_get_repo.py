async def github_get_repo(owner: str, repo: str) -> dict:
    """Get repo via the github API."""
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
    r = await _get(f'/repos/{owner}/{repo}', headers={'Accept': 'application/vnd.github+json'})
    return {'id': r['id'], 'name': r['name'], 'full_name': r['full_name'], 'description': r.get('description'), 'private': r['private'], 'url': r['html_url'], 'default_branch': r['default_branch'], 'created_at': r['created_at'], 'updated_at': r['updated_at'], 'language': r.get('language'), 'stars': r['stargazers_count'], 'forks': r['forks_count'], 'open_issues': r['open_issues_count'], 'topics': r.get('topics', [])}
