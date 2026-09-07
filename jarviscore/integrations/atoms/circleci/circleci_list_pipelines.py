from typing import Any, Dict, List, Optional
CIRCLECI_API = 'https://circleci.com/api/v2'

async def circleci_list_pipelines(project_slug: str, timeout: int=30, verify_ssl: bool=True, limit: int=25, base_url: str=None) -> dict:
    """List Pipelines via CircleCI API v2. Circle-Token auth. Official: https://circleci.com/docs/api/v2/operations/listPipelinesForProject.md"""
    try:
        if not project_slug:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'project_slug is required (e.g. gh/org/repo)'}
        api = _circleci_api_root(base_url)
        (headers, auth_err) = _circleci_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        (url, err) = _circleci_project_path(api, project_slug)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        url = url + '/pipeline'
        (records, status, message) = await _circleci_paginate_items(url, headers, limit, timeout, verify_ssl)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': message}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _circleci_api_root(base_url):
    root = (base_url or CIRCLECI_API).rstrip('/')
    if _host_is(root, 'circleci.com') and '/api/v2' not in root:
        root = root + '/api/v2' if not root.endswith('/api') else root + '/v2'
    return root

def _circleci_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _circleci_get(url, headers, params, timeout, verify_ssl):
    return await nexus_call('GET', url, headers=headers, params=params)

def _circleci_records(data, list_keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in list_keys:
            items = data.get(key)
            if isinstance(items, list):
                return items
        return [data]
    return []

def _circleci_project_path(api, project_slug):
    slug = (project_slug or '').strip().lstrip('/')
    if not slug:
        return (None, 'project_slug is required (e.g. gh/org/repo)')
    return (f'{api}/project/{slug}', None)

async def _circleci_paginate_items(url, headers, limit, timeout, verify_ssl, list_keys=('items',)):
    records = []
    page_token = None
    status = 0
    pages = 0
    while len(records) < limit and pages < 50:
        pages += 1
        params = {'page-token': page_token} if page_token else None
        resp = await _circleci_get(url, headers, params, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        batch = _circleci_records(data, list_keys)
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        if len(records) >= limit:
            break
        if isinstance(data, dict):
            page_token = data.get('next_page_token')
        else:
            page_token = None
        if not page_token:
            break
    return (records[:limit], status, 'ok')

def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or '').strip()
    if '://' not in u:
        u = 'https://' + u
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return any((host == d or host.endswith('.' + d) for d in domains))
