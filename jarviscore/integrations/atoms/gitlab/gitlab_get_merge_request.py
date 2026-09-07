from typing import Any, Dict, List, Optional
_GL_API_ROOT = 'https://gitlab.com/api/v4'

async def gitlab_get_merge_request(project_id: str, merge_request_iid: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a single merge request. Official: https://docs.gitlab.com/api/merge_requests/#get-single-mr"""
    try:
        (api, err) = _gl_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        if not project_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'project_id is required'}
        if not merge_request_iid:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'merge_request_iid is required'}
        (headers, auth_err) = _gl_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        pid = _gl_path_enc(project_id)
        iid = _gl_path_enc(merge_request_iid)
        (records, status, msg) = await _gl_get_entity(f'{api}/projects/{pid}/merge_requests/{iid}', headers, timeout, verify_ssl)
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

async def _gl_get_entity(url: str, headers: Dict[str, str], timeout: int, verify_ssl: bool, params: Optional[Dict[str, Any]]=None) -> tuple:
    resp = await nexus_call('GET', url, headers=headers, params=params)
    status = resp['status_code']
    if status >= 400:
        return ([], status, resp['body'][:1000])
    data = resp['json'] if resp['body'] else {}
    if isinstance(data, dict) and data:
        return ([data], status, 'ok')
    if isinstance(data, list):
        return ([x for x in data if isinstance(x, dict)], status, 'ok')
    return ([], status, 'Unexpected response format')
