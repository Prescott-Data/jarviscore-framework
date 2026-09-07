from typing import Any, Dict, List, Optional
_FS_API_HOST = 'https://api.fullstory.com'

async def fullstory_get_report(export_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get download URL for a completed segment export (GET /search/v1/exports/{exportId}/results). Authorization: Basic {api_key} from Settings > Integrations > API Keys (Architect for data reads). Official: https://developer.fullstory.com/"""
    try:
        if not export_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'export_id is required (searchExportId from operation results)'}
        api, err = _fs_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _fs_fullstory_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        url = f'{api}/search/v1/exports/{str(export_id).strip()}/results'
        resp = await nexus_call('GET', url, headers=headers)
        status = resp['status_code']
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        records = [data] if isinstance(data, dict) and data else []
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _fs_api_root(base_url: str):
    root = (base_url or _FS_API_HOST).rstrip('/')
    if not root:
        return (None, 'base_url is required (https://api.fullstory.com)')
    if 'fullstory.com' not in root:
        return (None, 'base_url must be the FullStory API host (https://api.fullstory.com)')
    return (root, None)

def _fs_fullstory_auth(json_body: bool=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)
