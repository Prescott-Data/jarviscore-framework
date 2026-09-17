from typing import Any, Dict, List, Optional

async def backblaze_b2_get_folder(folder_id: str, bucket_id: Optional[str]=None, bucket_name: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Resolve a folder prefix in a bucket via b2_list_file_names (B2 has no folder objects). Official: https://www.backblaze.com/b2/docs/b2_list_file_names.html"""
    try:
        if not base_url:
            base_url = _B2_DEFAULT_HOST
        if not folder_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'folder_id is required'}
        fail = _b2_auth_fail()
        if fail:
            return fail
        prefix = folder_id if folder_id.endswith('/') else folder_id + '/'
        (session, err) = await _b2_authorize(base_url, timeout, verify_ssl)
        if err != 'ok':
            return {'records': [], 'data_count': 0, 'status': 401, 'message': err}
        (bid, bid_err) = await _b2_resolve_bucket_id(session['api_url'], session['auth_token'], session['account_id'], bucket_id, bucket_name, timeout, verify_ssl, session.get('allowed_buckets'))
        if bid_err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': bid_err}
        body = {'bucketId': bid, 'prefix': prefix, 'maxFileCount': 1, 'delimiter': '/'}
        resp = await _b2_post(session['api_url'], '/b2api/v4/b2_list_file_names', session['auth_token'], body, timeout, verify_ssl)
        status = resp['status_code']
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        record = {'prefix': prefix, 'bucketId': bid}
        return {'records': [record], 'data_count': 1, 'status': status, 'message': 'ok'}
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
    (key_id, app_key, err) = _b2_credentials()
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

async def _b2_resolve_bucket_id(api_url, token, account_id, bucket_id, bucket_name, timeout, verify_ssl, allowed_buckets=None):
    if bucket_id:
        return (str(bucket_id), None)
    if not bucket_name:
        return (None, 'bucket_id or bucket_name is required')
    for bucket in allowed_buckets or []:
        if isinstance(bucket, dict) and bucket.get('name') == bucket_name and bucket.get('id'):
            return (str(bucket.get('id')), None)
    resp = await _b2_post(api_url, '/b2api/v4/b2_list_buckets', token, {'accountId': account_id}, timeout, verify_ssl)
    if resp['status_code'] >= 400:
        return (None, resp['body'][:1000])
    data = resp['json']
    for bucket in data.get('buckets') or []:
        if isinstance(bucket, dict) and bucket.get('bucketName') == bucket_name:
            return (str(bucket.get('bucketId')), None)
    return (None, f'bucket not found: {bucket_name}')

def _b2_auth_fail():
    (_, _, err) = _b2_credentials()
    if not err:
        return None
    return {'records': [], 'data_count': 0, 'status': 401, 'message': err}
