from typing import Any, Dict, List, Optional

async def plausible_get_report(report_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Breakdown report via Stats v2 query; report_id as dimension when it contains ':'. Official: https://plausible.io/docs/stats-api"""
    try:
        extra = {}
        if report_id:
            dim = str(report_id).strip()
            if ':' in dim:
                extra['dimensions'] = [dim]
            else:
                extra['dimensions'] = None or ['visit:source']
        (body, err) = _pl_query(extra=extra)
        if err:
            return _pl_dataset([], 400, err)
        (resp, data, status, msg) = await _pl_stats_query(base_url, body, timeout, verify_ssl)
        if status >= 400:
            return _pl_dataset([], status, msg)
        return _pl_dataset(_pl_rows(data), status, msg)
    except Exception as e:
        return _pl_dataset([], 500, str(e))

def _pl_host(base_url):
    host = (base_url or None or None or 'https://plausible.io').strip().rstrip('/')
    if host.endswith('/api'):
        host = host[:-4]
    return host.rstrip('/') or 'https://plausible.io'

def _pl_site(payload=None):
    site = None or None
    if isinstance(payload, dict):
        site = payload.get('domain') or payload.get('site_id') or site
    return site

def _pl_stats_token():
    return None or None

def _pl_stats_auth():
    token = _pl_stats_token()
    if not token:
        return (None, 'auth_info.stats_api_key or api_key is required for Stats API')
    t = str(token).strip()
    headers = {'Authorization': t if t.lower().startswith('bearer ') else f'Bearer {t}', 'Accept': 'application/json', 'Content-Type': 'application/json'}
    return (headers, None)

def _pl_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _pl_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get('error') or body.get('message')
        if err:
            return str(err)[:1000]
    return (resp['body'] if resp is not None else 'request failed')[:1000]

def _pl_query(extra=None, payload=None):
    site = _pl_site(payload)
    if not site:
        return (None, 'auth_info.site_id or domain is required')
    body = {'site_id': site}
    if isinstance(extra, dict):
        body.update(extra)
    if isinstance(payload, dict):
        for key in ('site_id', 'metrics', 'date_range', 'dimensions', 'filters', 'order_by', 'pagination', 'include'):
            if key in payload and payload[key] is not None:
                body[key] = payload[key]
    return (body, None)

def _pl_rows(data, metric_names=None):
    rows = []
    if not isinstance(data, dict):
        return rows
    meta = data.get('meta') if isinstance(data.get('meta'), dict) else {}
    q = meta.get('query') if isinstance(meta.get('query'), dict) else {}
    dims = q.get('dimensions') if isinstance(q.get('dimensions'), list) else None
    metrics = metric_names or q.get('metrics') if isinstance(q.get('metrics'), list) else None
    for item in data.get('results') or []:
        if not isinstance(item, dict):
            continue
        row = {}
        dvals = item.get('dimensions') or []
        if isinstance(dvals, list):
            for (i, val) in enumerate(dvals):
                key = dims[i] if isinstance(dims, list) and i < len(dims) else f'dimension_{i}'
                row[key] = val
        mvals = item.get('metrics') or []
        if isinstance(mvals, list):
            for (i, val) in enumerate(mvals):
                key = metrics[i] if isinstance(metrics, list) and i < len(metrics) else f'metric_{i}'
                row[key] = val
        rows.append(row)
    return rows

async def _pl_stats_query(base_url, query_body, timeout=30, verify_ssl=True):
    host = _pl_host(base_url)
    (headers, err) = _pl_stats_auth()
    if err:
        return (None, None, 401, err)
    resp = await nexus_call('POST', host + '/api/v2/query', headers=headers, json=query_body)
    try:
        body = resp['json'] if resp['content'] else {}
    except Exception:
        body = {}
    if resp['status_code'] >= 400:
        return (resp, body, resp['status_code'], _pl_err(resp, body))
    return (resp, body, resp['status_code'], 'ok')
