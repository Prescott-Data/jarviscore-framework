from typing import Any, Dict, List, Optional

async def backblaze_b2_get_file(file_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get file metadata by fileId (b2_get_file_info). Application key auth via b2_authorize_account. Official: https://www.backblaze.com/b2/docs/b2_get_file_info.html"""
    try:
        if not base_url:
            base_url = _B2_DEFAULT_HOST
        if not file_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'file_id is required'}
        fail = _b2_auth_fail()
        if fail:
            return fail
        session, err = await _b2_authorize(base_url, timeout, verify_ssl)
        if err != 'ok':
            return {'records': [], 'data_count': 0, 'status': 401, 'message': err}
        resp = await _b2_post(session['api_url'], '/b2api/v4/b2_get_file_info', session['auth_token'], {'fileId': file_id}, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        data = resp['json']
        records = [data] if isinstance(data, dict) else []
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}
_B2_DEFAULT_HOST = 'https://api.backblazeb2.com'

def _b2_credentials():
    return (None, None, None)

def _b2_authorize_host(base_url):
    host = (base_url or _B2_DEFAULT_HOST).rstrip('/')
    if host.endswith('/b2api/v4'):
        host = host.rsplit('/b2api', 1)[0]
    return host

async def _b2_authorize(base_url, timeout, verify_ssl):
    host = _b2_authorize_host(base_url)
    key_id, app_key, err = _b2_credentials()
    if err:
        return (None, err)
    resp = await nexus_call('GET', f'{host}/b2api/v4/b2_authorize_account', headers={'Accept': 'application/json'})
    if resp['status_code'] >= 400:
        return (None, resp['body'][:1000])
    data = resp['json']
    if not isinstance(data, dict):
        return (None, 'Unexpected authorize response')
    api_info = data.get('apiInfo') if isinstance(data.get('apiInfo'), dict) else {}
    storage = api_info.get('storageApi') if isinstance(api_info.get('storageApi'), dict) else {}
    api_url = storage.get('apiUrl') or data.get('apiUrl')
    allowed = storage.get('allowed') if isinstance(storage.get('allowed'), dict) else {}
    allowed_buckets = allowed.get('buckets') if isinstance(allowed.get('buckets'), list) else []
    if not api_url:
        return (None, 'Missing apiUrl in authorize response')
    return ({'api_url': str(api_url).rstrip('/'), 'auth_token': data.get('authorizationToken'), 'account_id': data.get('accountId'), 'allowed_buckets': allowed_buckets}, 'ok')

async def _b2_post(api_url, path, token, body, timeout, verify_ssl):
    return await nexus_call('POST', f'{api_url}{path}', headers={'Authorization': token, 'Content-Type': 'application/json', 'Accept': 'application/json'}, json=body)

def _b2_auth_fail():
    _, _, err = _b2_credentials()
    if not err:
        return None
    return {'records': [], 'data_count': 0, 'status': 401, 'message': err}
