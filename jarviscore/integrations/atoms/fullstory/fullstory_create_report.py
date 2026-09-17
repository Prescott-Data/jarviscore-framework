from typing import Any, Dict, List, Optional
_FS_API_HOST = 'https://api.fullstory.com'

async def fullstory_create_report(segment_id: str, export_type: str, format: str='FORMAT_CSV', time_range: Optional[Dict[str, Any]]=None, segment_time_range: Optional[Dict[str, Any]]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Schedule a segment export job (POST /segments/v1/exports). Poll GET /operations/v1/{operationId}, then fetch results. Authorization: Basic {api_key} from Settings > Integrations > API Keys (Architect for data reads). Official: https://developer.fullstory.com/"""
    try:
        if not segment_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'segment_id is required'}
        if not export_type:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'export_type is required (TYPE_EVENT, TYPE_INDIVIDUAL, etc.)'}
        (api, err) = _fs_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        body: Dict[str, Any] = {'segmentId': segment_id, 'type': export_type, 'format': format or 'FORMAT_CSV'}
        if time_range:
            body['timeRange'] = time_range
        if segment_time_range:
            body['segmentTimeRange'] = segment_time_range
        (headers, auth_err) = _fs_fullstory_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        resp = await nexus_call('POST', f'{api}/segments/v1/exports', headers=headers, json=body)
        status = resp['status_code']
        data = resp['json'] if resp['body'] else {}
        if status >= 400:
            return {'records': [], 'data_count': 0, 'status': status, 'message': resp['body'][:1000]}
        records = [data] if isinstance(data, dict) and data else []
        op_id = data.get('operationId') if isinstance(data, dict) else None
        provision = [str(op_id)] if op_id not in (None, '') else []
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok', 'provision_ids': provision}
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
