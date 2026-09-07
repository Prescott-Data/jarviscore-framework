from typing import Any, Dict, List, Optional
_GCS_API_ROOT = 'https://storage.googleapis.com/storage/v1'
_GCS_UPLOAD_ROOT = 'https://storage.googleapis.com/upload/storage/v1'

async def gcs_create_folder(bucket_name: str, folder_path: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create folder placeholder object (zero-byte object with trailing / name). OAuth Bearer token (cloud-platform or devstorage scope). JSON API root required. Official: https://cloud.google.com/storage/docs/json_api/v1"""
    try:
        if not folder_path:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'folder_path is required'}
        folder = _gcs_norm_prefix(folder_path)
        if not folder:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'folder_path is required'}
        (api, upload_api, err) = _gcs_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (bucket, err) = _gcs_bucket(bucket_name)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        (headers, auth_err) = _gcs_auth(content_type='application/x-www-form-urlencoded;charset=UTF-8')
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        params = {'uploadType': 'media', 'name': folder}
        resp = await nexus_call('POST', f'{upload_api}/b/{_gcs_pct_enc(bucket)}/o', headers=headers, params=params, data=b'')
        status = resp['status_code']
        data = resp['json'] if resp['body'] else {}
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        records = [data] if isinstance(data, dict) and data else [{'name': folder, 'prefix': folder}]
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok', 'provision_ids': [folder]}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _gcs_api_root(base_url: str):
    root = (base_url or _GCS_API_ROOT).rstrip('/')
    if not root:
        return (None, None, 'base_url is required (https://storage.googleapis.com/storage/v1)')
    if 'storage.googleapis.com' not in root or not root.endswith('/storage/v1'):
        return (None, None, 'base_url must be the GCS JSON API root (https://storage.googleapis.com/storage/v1)')
    upload = root.replace('/storage/v1', '/upload/storage/v1')
    return (root, upload, None)

def _gcs_bucket(bucket_name):
    bucket = bucket_name or None or None
    if bucket in (None, ''):
        return (None, 'bucket_name is required (or auth_info.bucket)')
    return (str(bucket).strip(), None)

def _gcs_auth(json_body: bool=False, content_type: Optional[str]=None):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    elif content_type:
        headers['Content-Type'] = content_type
    return (headers, None)

def _gcs_pct_enc(text: str) -> str:
    out = []
    for ch in str(text):
        o = ord(ch)
        if o < 128 and (ch.isalnum() or ch in '-_.~'):
            out.append(ch)
        else:
            for b in ch.encode('utf-8'):
                out.append(f'%{b:02X}')
    return ''.join(out)

def _gcs_norm_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ''
    p = str(prefix).replace('\\', '/').lstrip('/')
    return p if not p or p.endswith('/') else p + '/'
