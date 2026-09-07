from typing import Any, Dict, List, Optional

async def matomo_create_report(id_site: str, payload: Dict[str, Any], timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Create a scheduled report via ScheduledReports.addReport. Official: https://developer.matomo.org/api-reference/reporting-api#module_scheduledreports"""
    try:
        (site, serr) = _mt_id_site(id_site)
        if serr:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': serr, 'provision_ids': []}
        body = payload if isinstance(payload, dict) else {}
        description = body.get('description') or body.get('name')
        if not description:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload.description is required', 'provision_ids': []}
        params = {'idSite': site, 'description': description, 'period': body.get('period') or 'week', 'hour': body.get('hour', 0), 'reportType': body.get('reportType') or body.get('report_type') or 'email', 'reportFormat': body.get('reportFormat') or body.get('report_format') or 'html', 'reports': _mt_json_field(body.get('reports'), []), 'parameters': _mt_json_field(body.get('parameters'), {})}
        if body.get('idSegment') not in (None, ''):
            params['idSegment'] = body.get('idSegment')
        (resp, data, err) = await _mt_api_call(base_url, 'ScheduledReports.addReport', params, timeout, verify_ssl)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        status = resp['status_code']
        api_err = _mt_api_error(data, resp['body'])
        if status >= 400 or api_err:
            return {'records': [], 'data_count': 0, 'status': status if status >= 400 else 400, 'message': api_err or resp['body'][:1000], 'provision_ids': []}
        return _mt_provision(data, status)
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

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
    (root, err) = _mt_root(base)
    if err:
        return (None, None, err)
    (tok, terr) = _mt_token()
    if terr:
        return (None, None, terr)
    q = {'module': 'API', 'method': method, 'format': 'JSON', 'token_auth': tok}
    q.update({k: v for (k, v) in (params or {}).items() if v not in (None, '')})
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

def _mt_json_field(value, default):
    if isinstance(value, str):
        return value
    import json
    return json.dumps(value if value is not None else default)

def _mt_provision(data, status, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    obj_id = obj.get('value') or obj.get('idReport') or obj.get('id') or fallback_id
    ids = [obj_id] if obj_id not in (None, '') else []
    records = [obj] if obj else [{'idReport': obj_id}] if obj_id else []
    return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok' if status < 400 else _mt_api_error(data, str(obj))[:1000], 'provision_ids': ids}
