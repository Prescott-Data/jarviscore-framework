from typing import Any, Dict, List, Optional
ATOM_POLICY = {"effect": "destructive", "approval": "required", "idempotency_fields": ["customer_id", "criterion_id"], "consequence": "Removes the Google Ads keyword criterion."}
_GADS_API_ROOT = 'https://googleads.googleapis.com/v24'

async def google_ads_remove_keyword(customer_id: str, criterion_id: str, resource_name: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Remove a keyword in google ads. Official: https://developers.google.com/google-ads/api/rest/reference/rest/v24/customers.adGroupCriteria/mutate"""
    try:
        (api, err) = _gads_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        (cid, err) = _gads_customer_id(customer_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        (headers, auth_err) = _gads_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        rn = resource_name
        if not rn and criterion_id:
            (rn, status, msg) = await _gads_resolve_criterion(api, cid, headers, criterion_id, timeout, verify_ssl)
            if not rn:
                return {'records': [], 'data_count': 0, 'status': status or 404, 'message': msg or 'keyword not found', 'provision_ids': []}
        if not rn:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'resource_name or criterion_id is required', 'provision_ids': []}
        body = {'operations': [{'remove': rn}]}
        (data, status, msg) = await _gads_mutate(api, cid, 'adGroupCriteria', headers, body, timeout, verify_ssl)
        if status >= 400 or msg != 'ok':
            return {'records': [], 'data_count': 0, 'status': status, 'message': msg, 'provision_ids': []}
        return _gads_provision_response(data, status)
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e), 'provision_ids': []}

def _gads_api_root(base_url: str):
    root = (base_url or _GADS_API_ROOT).rstrip('/')
    if 'googleads.googleapis.com' not in root:
        return (None, 'base_url must be Google Ads API root (https://googleads.googleapis.com/v24)')
    return (root, None)

def _gads_customer_id(customer_id: Optional[str]):
    cid = customer_id or None or None
    if cid in (None, ''):
        return (None, 'customer_id is required (or auth_info.customer_id)')
    return (str(cid).replace('-', ''), None)

def _gads_auth(json_body: bool=False) -> tuple:
    headers = {'Accept': 'application/json'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    dev = None or None
    if dev:
        headers['developer-token'] = str(dev)
    login = None or None
    if login not in (None, ''):
        headers['login-customer-id'] = str(login).replace('-', '')
    return (headers, None)

async def _gads_search(api: str, customer_id: str, headers: Dict[str, str], query: str, limit: int, timeout: int, verify_ssl: bool) -> tuple:
    records: List[Dict[str, Any]] = []
    cap = min(max(int(limit or 25), 1), 10000)
    page_token = None
    status = 0
    url = f'{api}/customers/{customer_id}/googleAds:search'
    while len(records) < cap:
        body: Dict[str, Any] = {'query': query}
        if page_token:
            body['pageToken'] = page_token
        resp = await nexus_call('POST', url, headers=headers, json=body)
        status = resp['status_code']
        if status >= 400:
            return (records, status, resp['body'][:1000])
        data = resp['json'] if resp['body'] else {}
        rows = data.get('results') if isinstance(data, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    records.append(row)
                    if len(records) >= cap:
                        break
        page_token = data.get('nextPageToken') if isinstance(data, dict) else None
        if not page_token or len(records) >= cap:
            break
    return (records, status, 'ok')

async def _gads_mutate(api: str, customer_id: str, resource: str, headers: Dict[str, str], body: Dict[str, Any], timeout: int, verify_ssl: bool) -> tuple:
    url = f'{api}/customers/{customer_id}/{resource}:mutate'
    resp = await nexus_call('POST', url, headers=headers, json=body)
    status = resp['status_code']
    data = resp['json'] if resp['content'] else {}
    if status >= 400:
        msg = data if isinstance(data, dict) else resp['body'][:1000]
        return (data, status, str(msg))
    return (data, status, 'ok')

def _gads_provision_ids(data: Any) -> List[Any]:
    ids: List[Any] = []
    if not isinstance(data, dict):
        return ids
    for row in data.get('results') or []:
        if not isinstance(row, dict):
            continue
        for key in ('resourceName', 'resource_name'):
            if row.get(key):
                ids.append(row.get(key))
                break
    return ids

def _gads_provision_response(data: Any, status: int) -> Dict[str, Any]:
    records = [data] if isinstance(data, dict) else []
    provision_ids = _gads_provision_ids(data)
    return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok', 'provision_ids': provision_ids}

async def _gads_resolve_criterion(api, cid, headers, criterion_id, timeout, verify_ssl):
    query = f'SELECT ad_group_criterion.resource_name FROM ad_group_criterion WHERE ad_group_criterion.criterion_id = {criterion_id} LIMIT 1'
    (rows, status, msg) = await _gads_search(api, cid, headers, query, 1, timeout, verify_ssl)
    if status >= 400 or not rows:
        return (None, status, msg)
    crit = rows[0].get('adGroupCriterion') or rows[0].get('ad_group_criterion') or {}
    return (crit.get('resourceName') or crit.get('resource_name'), status, 'ok')
