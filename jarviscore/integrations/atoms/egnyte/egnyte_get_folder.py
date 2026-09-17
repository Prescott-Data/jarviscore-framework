from typing import Any, Dict, List, Optional
_EGNYTE_PUBAPI_SUFFIX = '/pubapi/v1'

async def egnyte_get_folder(folder_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get folder metadata (GET /pubapi/v1/fs/{path}). folder_id is the Egnyte path. Bearer OAuth per Egnyte Public API. Official: https://developers.egnyte.com/docs/read/File_System_Management_API_Documentation"""
    try:
        if not folder_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'folder_id is required (Egnyte folder path, e.g. /Shared/Documents)'}
        (api, err) = _egnyte_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _egnyte_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await nexus_call('GET', _egnyte_fs_url(api, folder_id), headers=headers)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = [data] if isinstance(data, dict) else []
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _egnyte_api_root(base_url: str):
    root = (base_url or '').rstrip('/')
    if not root:
        return (None, 'base_url is required (https://{domain}.egnyte.com/pubapi/v1)')
    if _EGNYTE_PUBAPI_SUFFIX not in root:
        return (None, 'base_url must be the Egnyte pubapi v1 root (https://{domain}.egnyte.com/pubapi/v1)')
    return (root, None)

def _egnyte_auth(json_body: bool=False, content: bool=False):
    headers: Dict[str, str] = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    elif content:
        headers['Content-Type'] = 'application/octet-stream'
    return (headers, None)

def _egnyte_pct_enc(text: str) -> str:
    out = []
    for ch in str(text):
        o = ord(ch)
        if o < 128 and (ch.isalnum() or ch in '-_.~'):
            out.append(ch)
        else:
            for b in ch.encode('utf-8'):
                out.append(f'%{b:02X}')
    return ''.join(out)

def _egnyte_fs_url(api: str, path: str) -> str:
    raw = str(path or '/')
    if not raw.startswith('/'):
        raw = '/' + raw
    parts = [p for p in raw.split('/') if p]
    if not parts:
        return f'{api}/fs/'
    return f'{api}/fs/' + '/'.join((_egnyte_pct_enc(p) for p in parts))
