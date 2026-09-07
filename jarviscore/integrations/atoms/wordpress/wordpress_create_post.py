from typing import Any, Dict, List, Optional

async def wordpress_create_post(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """wordpress REST: create post. Official: https://developer.wordpress.org/rest-api/"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _provision({}, 400, 'payload is required (e.g. title, content, status)')
        (root, err) = _root(base_url)
        if err:
            return _provision({}, 400, err)
        (headers, aerr) = _auth()
        if isinstance(headers, str) or aerr:
            return _provision({}, 401, aerr or headers)
        auth = headers if isinstance(headers, tuple) else None
        hdrs = headers if isinstance(headers, dict) else {'Accept': 'application/json'}
        resp = await nexus_call('POST', root + '/posts', headers=hdrs, json=payload)
        if resp['status_code'] >= 400:
            return _provision({}, resp['status_code'], _err(resp))
        data = resp['json'] if resp['content'] else {}
        return _provision(data if isinstance(data, dict) else {}, resp['status_code'], 'ok')
    except Exception as e:
        return _provision({}, 500, str(e))

def _root(base_url):
    root = (base_url or None or 'https://example.com/wp-json/wp/v2').strip().rstrip('/')
    if not root:
        return (None, 'base_url is required')
    return (root, None)

def _auth():
    return (None, 'auth_info requires username and password')

def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _err(resp):
    return (resp['body'] or 'HTTP ' + str(resp['status_code']))[:1000]
