from typing import Any, Dict, List, Optional
MP_INGEST = 'https://api.mixpanel.com'
MP_QUERY = 'https://mixpanel.com/api/query'
MP_EXPORT = 'https://data.mixpanel.com/api/2.0'

async def mixpanel_create_event(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Track an event via Ingestion API /track. Official: https://developer.mixpanel.com/reference/track-event"""
    try:
        (root, _) = _mp_ingest_root(base_url)
        (tok, terr) = _mp_project_token(payload)
        if terr:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': terr, 'provision_ids': []}
        body = payload if isinstance(payload, dict) else {}
        event_name = body.get('event') or body.get('name')
        if not event_name:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload.event is required', 'provision_ids': []}
        props = dict(body.get('properties') if isinstance(body.get('properties'), dict) else body)
        props.pop('event', None)
        props.pop('name', None)
        props['token'] = tok
        if body.get('distinct_id') and 'distinct_id' not in props:
            props['distinct_id'] = body.get('distinct_id')
        track = [{'event': str(event_name), 'properties': props}]
        resp = await nexus_call('POST', f'{root}/track', params={'verbose': '1'}, json=track)
        insert_id = props.get('$insert_id') or props.get('insert_id')
        fallback = insert_id or f"{event_name}|{props.get('distinct_id', '')}"
        return _mp_provision(resp, fallback_id=fallback)
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

def _mp_ingest_root(base_url):
    return ((base_url or MP_INGEST).rstrip('/'), None)

def _mp_project_token(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    tok = None or None or payload.get('token') or payload.get('$token')
    if not tok:
        return (None, 'auth_info.project_token is required')
    return (str(tok), None)

def _mp_error_text(resp):
    try:
        data = resp['json']
        if isinstance(data, dict):
            if data.get('error'):
                return str(data.get('error'))[:1000]
            if data.get('status') == 'error':
                return str(data.get('error') or data)[:1000]
    except Exception:
        pass
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _mp_provision_ids_from_body(body, fallback=None):
    if isinstance(body, dict):
        props = body.get('properties') if isinstance(body.get('properties'), dict) else {}
        for key in ('$insert_id', 'insert_id', 'id', '$distinct_id', 'distinct_id'):
            val = body.get(key) or props.get(key)
            if val not in (None, ''):
                return [val]
    return [fallback] if fallback not in (None, '') else []

def _mp_provision(resp, fallback_id=None):
    status = resp['status_code']
    if status >= 400:
        return {'records': [], 'data_count': 0, 'status': status, 'message': _mp_error_text(resp), 'provision_ids': []}
    body = {}
    try:
        if resp['body']:
            body = resp['json']
    except Exception:
        body = {'raw': resp['body'][:200]}
    if isinstance(body, int):
        if body != 1:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'Mixpanel rejected payload', 'provision_ids': []}
        ids = [fallback_id] if fallback_id not in (None, '') else []
        rec = {'id': fallback_id} if ids else []
        return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': 'ok', 'provision_ids': ids}
    ids = _mp_provision_ids_from_body(body, fallback_id)
    records = [body] if isinstance(body, dict) and body else [{'id': ids[0]}] if ids else []
    return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok', 'provision_ids': ids}
