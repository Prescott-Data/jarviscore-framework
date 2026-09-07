from typing import Any, Dict, List, Optional
_GADS_API_ROOT = 'https://googleads.googleapis.com/v24'

async def google_ads_get_ad_group(customer_id: str, ad_group_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Get a ad group in google ads. Official: https://developers.google.com/google-ads/api/docs/rest/common/search"""
    try:
        api, err = _gads_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        cid, err = _gads_customer_id(customer_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        if not ad_group_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'ad_group_id is required'}
        headers, auth_err = _gads_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        query = f'SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.type, ad_group.campaign, ad_group.cpc_bid_micros, ad_group.resource_name FROM ad_group WHERE ad_group.id = {ad_group_id}'
        records, status, msg = await _gads_search(api, cid, headers, query, 1, timeout, verify_ssl)
        if status >= 400 or msg != 'ok':
            return {'records': [], 'data_count': 0, 'status': status, 'message': msg}
        return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

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
