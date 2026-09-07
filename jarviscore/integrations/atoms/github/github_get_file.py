async def github_get_file(owner: str, repo: str, path: str, ref: str=None) -> dict:
    """Get file via the github API."""
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
    import base64
    params = {}
    if ref:
        params['ref'] = ref
    f = await _get(f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}", params=params, headers={'Accept': 'application/vnd.github+json'})
    content = base64.b64decode(f['content']).decode('utf-8') if f.get('encoding') == 'base64' else f.get('content', '')
    return {'name': f['name'], 'path': f['path'], 'sha': f['sha'], 'size': f['size'], 'url': f['html_url'], 'content': content}
