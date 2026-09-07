from typing import Any, Dict, List, Optional
_GL_API_ROOT = 'https://gitlab.com/api/v4'

async def gitlab_list_merge_requests(project_id: str, max_results: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List project merge requests. Official: https://docs.gitlab.com/api/merge_requests/#list-project-merge-requests"""
    try:
        api, err = _gl_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        if not project_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'project_id is required'}
        headers, auth_err = _gl_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        pid = _gl_path_enc(project_id)
        records, status, msg = await _gl_paginate_list(f'{api}/projects/{pid}/merge_requests', headers, max_results, timeout, verify_ssl)
        if status >= 400 or msg != 'ok':
            return {'records': records, 'data_count': len(records), 'status': status, 'message': msg}
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        err = {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}
        return err

def _gl_api_root(base_url: str):
    root = (base_url or _GL_API_ROOT).rstrip('/')
    if not root.endswith('/api/v4'):
        return (None, 'base_url must end with /api/v4 (e.g. https://gitlab.com/api/v4)')
    return (root, None)

def _gl_auth(json_body: bool=False) -> tuple:
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

def _gl_path_enc(text: str) -> str:
    out: List[str] = []
    for ch in str(text):
        o = ord(ch)
        if o < 128 and (ch.isalnum() or ch in '-_.~'):
            out.append(ch)
        else:
            for b in ch.encode('utf-8'):
                out.append(f'%{b:02X}')
    return ''.join(out)

def _gl_link_next(link_header: str) -> Optional[str]:
    if not link_header or 'rel="next"' not in link_header:
        return None
    for part in link_header.split(','):
        if 'rel="next"' in part:
            return part.split(';')[0].strip().strip('<> ')
    return None

async def _gl_paginate_list(url: str, headers: Dict[str, str], limit: int, timeout: int, verify_ssl: bool, params: Optional[Dict[str, Any]]=None) -> tuple:
    records: List[Dict[str, Any]] = []
    cap = min(max(int(limit or 25), 1), 1000)
    page = 1
    status = 0
    base_params = dict(params or {})
    while len(records) < cap:
        q = dict(base_params)
        q['per_page'] = min(100, cap - len(records))
        q['page'] = page
        resp = await nexus_call('GET', url, headers=headers, params=q)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json']
        if not isinstance(data, list):
            return (records, status, 'Unexpected response format')
        if not data:
            break
        for item in data:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        if len(records) >= cap or not _gl_link_next(resp['headers'].get('Link', '')):
            break
        page += 1
    return (records, status, 'ok')
