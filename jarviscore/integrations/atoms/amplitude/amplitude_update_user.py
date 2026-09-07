from typing import Any, Dict, List, Optional

async def amplitude_update_user(user_id: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update user properties via Identify API (POST https://api2.amplitude.com/identify). Official: https://www.docs.developers.amplitude.com/analytics/apis/identify-api/"""
    try:
        if not base_url:
            return _amp_provision([], 400, 'base_url is required')
        if not user_id:
            return _amp_provision([], 400, 'user_id is required')
        if not isinstance(payload, dict):
            return _amp_provision([], 400, 'payload must be a dict')
        _, dash_host, root_err = _amp_dashboard_root(base_url)
        if root_err:
            return _amp_provision([], 400, root_err)
        api_key = _amp_api_key()
        if not api_key:
            return _amp_provision([], 401, 'auth_info.api_key is required for Identify API')
        user_props = payload.get('user_properties') if isinstance(payload.get('user_properties'), dict) else payload
        ident = [{'user_id': str(user_id), 'user_properties': user_props}]
        form = {'api_key': str(api_key), 'identification': _json_dumps(ident)}
        url = f'{_amp_ingest_root(dash_host)}/identify'
        resp = await nexus_call('POST', url, data=form)
        status = resp['status_code']
        try:
            data = resp['json'] if resp['content'] else {'raw': resp['body'][:1000]}
        except Exception:
            data = {'raw': resp['body'][:1000]}
        if status >= 400:
            return _amp_provision([], status, _amp_msg(data) or _amp_err(resp))
        rec = data if isinstance(data, dict) else {}
        return _amp_provision([rec] if rec else [], status, 'ok', [str(user_id)])
    except Exception as e:
        return _amp_provision([], 500, str(e))

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
_AMP_DASHBOARD_SUFFIX = '/api/2'
_AMP_DASHBOARD_HOSTS = {'https://amplitude.com', 'https://analytics.eu.amplitude.com'}
_AMP_INGEST_HOSTS = {'https://amplitude.com': 'https://api2.amplitude.com', 'https://analytics.eu.amplitude.com': 'https://api.eu.amplitude.com'}

def _amp_dashboard_root(base_url: str):
    root = base_url.rstrip('/')
    if not root.endswith(_AMP_DASHBOARD_SUFFIX):
        return (None, None, 'base_url must be https://amplitude.com/api/2 or https://analytics.eu.amplitude.com/api/2')
    host = root[:-len(_AMP_DASHBOARD_SUFFIX)]
    if host not in _AMP_DASHBOARD_HOSTS:
        return (None, None, 'base_url must be https://amplitude.com/api/2 or https://analytics.eu.amplitude.com/api/2')
    return (root, host, None)

def _amp_ingest_root(dashboard_host: str) -> str:
    return _AMP_INGEST_HOSTS.get(dashboard_host, 'https://api2.amplitude.com')

def _amp_api_key():
    return None

def _amp_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg, 'provision_ids': ids}

def _amp_err(resp):
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _amp_msg(data):
    if isinstance(data, dict):
        err = data.get('error') or data.get('message')
        if err:
            return str(err)[:1000]
    return str(data)[:1000] if data else 'request failed'
