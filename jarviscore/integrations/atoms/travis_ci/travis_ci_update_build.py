from typing import Any, Dict, List, Optional
_TR_ROOT = 'https://api.travis-ci.com'

async def travis_ci_update_build(build_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Travis CI API v3: update build. Official: https://developer.travis-ci.com/resource"""
    try:
        (root, err) = _tr_root(base_url)
        if err:
            return _tr_provision({}, 400, err)
        if not build_id:
            return _tr_provision({}, 400, 'build_id is required')
        (headers, aerr) = _tr_auth()
        if aerr:
            return _tr_provision({}, 401, aerr)
        resp = await nexus_call('POST', f'{root}/build/{build_id}/cancel', headers=headers)
        if resp['status_code'] >= 400:
            return _tr_provision({}, resp['status_code'], _tr_err(resp))
        return _tr_provision({'id': build_id}, resp['status_code'], 'ok', fallback_id=build_id)
    except Exception as e:
        return _tr_provision({}, 500, str(e))

def _tr_root(base_url):
    root = (base_url or None or _TR_ROOT).strip().rstrip('/')
    return (root, None)

def _tr_auth():
    return ({'Accept': 'application/json', 'Travis-API-Version': '3'}, None)

def _tr_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get('id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = obj if obj else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _tr_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]
