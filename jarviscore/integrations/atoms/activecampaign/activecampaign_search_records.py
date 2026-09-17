from typing import Any, Dict, List, Optional

async def activecampaign_search_records(query: str, account: Optional[str]=None, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search contacts via GET /contacts?search= (names, org, phone, email). Official: https://developers.activecampaign.com/reference/list-all-contacts"""
    try:
        if not query:
            return _ac_v3_dataset([], 400, 'query is required')
        (api_root, err) = _ac_v3_resolve_base(base_url, account)
        if err:
            return _ac_v3_dataset([], 400, err)
        (headers, err) = _ac_v3_headers()
        if err:
            return _ac_v3_dataset([], 401, err)
        cap = _ac_v3_cap(limit)
        records: List[Dict[str, Any]] = []
        offset = 0
        status = 200
        while len(records) < cap:
            page_size = min(cap - len(records), 100)
            resp = await nexus_call('GET', f'{api_root}/contacts', headers=headers, params={'search': query, 'limit': page_size, 'offset': offset})
            status = resp['status_code']
            if status >= 400:
                return _ac_v3_dataset(records, status, _ac_v3_err(resp))
            try:
                data = resp['json']
            except Exception:
                return _ac_v3_dataset(records, status, 'invalid JSON response')
            batch = data.get('contacts') if isinstance(data, dict) else None
            if not isinstance(batch, list):
                return _ac_v3_dataset(records, status, 'missing contacts array in response')
            for item in batch:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        break
            if len(batch) < page_size:
                break
            offset += page_size
        return _ac_v3_dataset(records[:cap], status, 'ok')
    except Exception as e:
        return _ac_v3_dataset([], 500, str(e))

def _ac_v3_resolve_base(base_url, account):
    if base_url:
        root = str(base_url).strip().rstrip('/')
    elif True .get('api_base'):
        root = str(None).strip().rstrip('/')
    elif account:
        region = None or None or 'us1'
        root = f'https://{account}.api-{region}.com/api/3'
    else:
        return (None, 'base_url or account is required')
    if not root.endswith('/api/3'):
        return (None, 'base_url must be the v3 root ending in /api/3')
    return (root, None)

def _ac_v3_headers():
    return ({'Accept': 'application/json'}, None)

def _ac_v3_cap(limit):
    return min(max(int(limit or 25), 1), 100)

def _ac_v3_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _ac_v3_err(resp):
    return (resp['body'] if resp is not None else 'request failed')[:1000]
