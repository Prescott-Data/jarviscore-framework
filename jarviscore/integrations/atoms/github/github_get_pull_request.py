async def github_get_pull_request(owner: str, repo: str, pull_number: int) -> dict:
    """Get pull request via the github API."""
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
    pr = await _get(f'/repos/{owner}/{repo}/pulls/{pull_number}', headers={'Accept': 'application/vnd.github+json'})
    return {'number': pr['number'], 'title': pr['title'], 'state': pr['state'], 'body': pr.get('body'), 'url': pr['html_url'], 'user': pr['user']['login'], 'head': pr['head']['ref'], 'base': pr['base']['ref'], 'draft': pr.get('draft', False), 'mergeable': pr.get('mergeable'), 'merged': pr.get('merged', False), 'commits': pr.get('commits'), 'additions': pr.get('additions'), 'deletions': pr.get('deletions'), 'changed_files': pr.get('changed_files'), 'created_at': pr['created_at'], 'updated_at': pr['updated_at']}
