from typing import Any, Dict, List, Optional

async def box_create_file(file_name: str, timeout: int=30, verify_ssl: bool=True, parent_folder_id: str='0', content: str='', base_url: str=None) -> dict:
    """Upload a new file (POST upload.box.com/api/2.0/files/content). Official: https://developer.box.com/reference/post-files-content/"""
    try:
        if not file_name:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'file_name is required', 'provision_ids': []}
        headers, auth_err = _box_auth()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err, 'provision_ids': []}
        headers.pop('Content-Type', None)
        attributes = _json_dumps({'name': file_name, 'parent': {'id': parent_folder_id}})
        files = {'attributes': (None, attributes, 'application/json'), 'file': (file_name, content.encode('utf-8') if isinstance(content, str) else b'', 'application/octet-stream')}
        resp = await nexus_call('POST', f'{BOX_UPLOAD}/files/content', headers=headers, files=files)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000], 'provision_ids': []}
        data = resp['json'] if resp['body'] else {}
        entries = data.get('entries') if isinstance(data, dict) else []
        file_obj = entries[0] if isinstance(entries, list) and entries else data
        prov = [file_obj.get('id')] if isinstance(file_obj, dict) and file_obj.get('id') else []
        return {'records': [file_obj] if file_obj else [], 'data_count': 1 if file_obj else 0, 'status': resp['status_code'], 'message': 'ok', 'provision_ids': prov}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

def _json_escape(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

def _json_dumps(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{_json_escape(value)}"'
    if isinstance(value, dict):
        parts = [f'"{_json_escape(k)}": {_json_dumps(v)}' for k, v in value.items()]
        return '{' + ', '.join(parts) + '}'
    if isinstance(value, list):
        return '[' + ', '.join((_json_dumps(v) for v in value)) + ']'
    return f'"{_json_escape(str(value))}"'
BOX_API = 'https://api.box.com/2.0'
BOX_UPLOAD = 'https://upload.box.com/api/2.0'

def _box_auth(json_body=False):
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)
