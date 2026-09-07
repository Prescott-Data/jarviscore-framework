from typing import Any, Dict, List, Optional

async def matomo_get_event(id_site: str, event_id: str, period: str='day', date: str='today', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get event actions for a category idSubtable via Events.getActionFromCategoryId. Official: https://developer.matomo.org/api-reference/reporting-api#module_events"""
    try:
        if not event_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'event_id is required (idSubtable from list_events)'}
        site, serr = _mt_id_site(id_site)
        if serr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': serr}
        resp, data, err = await _mt_api_call(base_url, 'Events.getActionFromCategoryId', {'idSite': site, 'period': period or 'day', 'date': date or 'today', 'idSubtable': str(event_id)}, timeout, verify_ssl)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        status = resp['status_code']
        api_err = _mt_api_error(data, resp['body'])
        if status >= 400 or api_err:
            return {'records': [], 'data_count': 0, 'status': status if status >= 400 else 400, 'message': api_err or resp['body'][:1000]}
        records = _mt_rows(data)
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _mt_root(base_url):
    if not base_url:
        return (None, 'base_url is required')
    return (base_url.rstrip('/'), None)

def _mt_token():
    return (None, None)

def _mt_id_site(id_site):
    site = id_site or None or None or None
    if site in (None, ''):
        return (None, 'id_site is required')
    return (str(site), None)

async def _mt_api_call(base, method, params, timeout, verify_ssl):
    root, err = _mt_root(base)
    if err:
        return (None, None, err)
    tok, terr = _mt_token()
    if terr:
        return (None, None, terr)
    q = {'module': 'API', 'method': method, 'format': 'JSON', 'token_auth': tok}
    q.update({k: v for k, v in (params or {}).items() if v not in (None, '')})
    resp = await nexus_call('GET', f'{root}/index.php', params=q)
    try:
        data = resp['json'] if resp['body'] else {}
    except Exception:
        data = {'result': 'error', 'message': resp['body'][:1000]}
    return (resp, data, None)

def _mt_api_error(data, fallback=''):
    if isinstance(data, dict) and data.get('result') == 'error':
        return str(data.get('message') or fallback)[:1000]
    return ''

def _mt_rows(data):
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        if data.get('result') == 'error':
            return []
        for key in ('reportData', 'reports', 'value'):
            val = data.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
        if data.get('label') is not None or data.get('idsubdatatable') is not None:
            return [data]
    return []
