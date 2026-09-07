from typing import Any, Dict, List, Optional

async def streak_search_records(query: str, pipeline_key: str='', limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Streak API: search boxes in pipeline client-side. Official: https://streak.com/api#get_boxes_in_pipeline"""
    try:
        if not query:
            return _st_dataset([], 400, 'query is required')
        (root, _) = _st_root(base_url)
        (headers, err) = _st_auth()
        if err:
            return _st_dataset([], 401, err)
        params = {'query': str(query)}
        pk = pipeline_key or None
        if pk:
            params['pipelineKey'] = pk
        resp = await nexus_call('GET', root + '/search', headers=headers, params=params)
        try:
            data = resp['json'] if resp['content'] else {}
        except Exception:
            data = {}
        if resp['status_code'] >= 400:
            return _st_dataset([], resp['status_code'], _st_err(resp))
        records = _st_search_results(data)[:_st_cap(limit)]
        return _st_dataset(records, resp['status_code'], 'ok')
    except Exception as e:
        return _st_dataset([], 500, str(e))

def _st_root(base_url):
    root = (base_url or None or None or 'https://www.streak.com/api/v1').strip().rstrip('/')
    if not root.endswith('/v1'):
        if _host_is(root, 'streak.com') and '/v1' not in root:
            root = root + '/api/v1' if '/api' not in root else root + '/v1'
    return (root, None)

def _st_auth():
    import base64
    return ({'Accept': 'application/json'}, None)

def _st_cap(limit):
    return min(max(int(limit or 25), 1), 1000)

def _st_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _st_err(resp):
    return (resp['body'] or f"HTTP {resp['status_code']}")[:1000]

def _st_search_results(data):
    out = []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        results = data.get('results') if isinstance(data.get('results'), (dict, list)) else data
        if isinstance(results, list):
            return [x for x in results if isinstance(x, dict)]
        if isinstance(results, dict):
            for key in ('boxes', 'contacts', 'organizations'):
                val = results.get(key)
                if isinstance(val, list):
                    out.extend([x for x in val if isinstance(x, dict)])
    return out

def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or '').strip()
    if '://' not in u:
        u = 'https://' + u
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return any((host == d or host.endswith('.' + d) for d in domains))
