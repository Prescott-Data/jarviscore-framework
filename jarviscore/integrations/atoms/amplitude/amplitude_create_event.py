from typing import Any, Dict, List, Optional

async def amplitude_create_event(payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Ingest analytics events (POST https://api2.amplitude.com/2/httpapi). Official: https://www.docs.developers.amplitude.com/analytics/apis/http-v2-api/"""
    try:
        if not base_url:
            return _amp_provision([], 400, 'base_url is required')
        if not isinstance(payload, dict) or not payload:
            return _amp_provision([], 400, 'payload must be a non-empty dict')
        _, dash_host, root_err = _amp_dashboard_root(base_url)
        if root_err:
            return _amp_provision([], 400, root_err)
        api_key = _amp_api_key()
        if not api_key:
            return _amp_provision([], 401, 'auth_info.api_key is required for event ingestion')
        events = payload.get('events') if isinstance(payload.get('events'), list) else [payload]
        body = {'api_key': str(api_key), 'events': events}
        url = f'{_amp_ingest_root(dash_host)}/2/httpapi'
        resp = await nexus_call('POST', url, json=body)
        status = resp['status_code']
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {'message': resp['body'][:1000]}
        if status >= 400:
            return _amp_provision([], status, _amp_msg(data) or _amp_err(resp))
        rec = data if isinstance(data, dict) else {}
        ids = _amp_event_provision_ids(events)
        return _amp_provision([rec] if rec else [], status, 'ok', ids)
    except Exception as e:
        return _amp_provision([], 500, str(e))
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

def _amp_event_provision_ids(events):
    ids = []
    for ev in events if isinstance(events, list) else []:
        if not isinstance(ev, dict):
            continue
        iid = ev.get('insert_id') or ev.get('$insert_id')
        if iid not in (None, ''):
            ids.append(str(iid))
    return ids
