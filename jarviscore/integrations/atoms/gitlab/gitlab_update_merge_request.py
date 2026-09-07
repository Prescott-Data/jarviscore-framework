from typing import Any, Dict, List, Optional
_GL_API_ROOT = 'https://gitlab.com/api/v4'

async def gitlab_update_merge_request(project_id: str, merge_request_iid: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update a merge request. Official: https://docs.gitlab.com/api/merge_requests/#update-mr"""
    try:
        (api, err) = _gl_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        if not project_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'project_id is required', 'provision_ids': []}
        if not merge_request_iid:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'merge_request_iid is required', 'provision_ids': []}
        if not isinstance(payload, dict) or not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required', 'provision_ids': []}
        (headers, auth_err) = _gl_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        pid = _gl_path_enc(project_id)
        iid = _gl_path_enc(merge_request_iid)
        resp = await nexus_call('PUT', f'{api}/projects/{pid}/merge_requests/{iid}', headers=headers, json=payload)
        status = resp['status_code']
        data = resp['json'] if resp['content'] else {}
        if status >= 400:
            msg = data if isinstance(data, dict) else resp['body'][:1000]
            return {'records': [], 'data_count': 0, 'status': status, 'message': str(msg), 'provision_ids': []}
        return _gl_provision_response(data, status, id_keys=('id', 'iid'))
    except Exception as e:
        err = {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}
        err['provision_ids'] = []
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

def _gl_provision_response(data: Any, status: int, id_keys=('id', 'iid')) -> Dict[str, Any]:
    records = [data] if isinstance(data, dict) else []
    provision_ids: List[Any] = []
    if isinstance(data, dict):
        for key in id_keys:
            val = data.get(key)
            if val not in (None, ''):
                provision_ids = [val]
                break
    return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok', 'provision_ids': provision_ids}
