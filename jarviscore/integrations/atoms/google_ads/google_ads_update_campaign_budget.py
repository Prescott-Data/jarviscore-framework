from typing import Any, Dict, List, Optional
_GADS_API_ROOT = 'https://googleads.googleapis.com/v24'

async def google_ads_update_campaign_budget(customer_id: str, budget_id: str, payload: Dict[str, Any], update_mask: Optional[str]=None, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Update a campaign budget in google ads. Official: https://developers.google.com/google-ads/api/rest/reference/rest/v24/customers.campaignBudgets/mutate"""
    try:
        api, err = _gads_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        cid, err = _gads_customer_id(customer_id)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err, 'provision_ids': []}
        if not budget_id:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'budget_id is required', 'provision_ids': []}
        if not isinstance(payload, dict) or not payload:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'payload is required', 'provision_ids': []}
        headers, auth_err = _gads_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        if isinstance(payload.get('operations'), list):
            body = payload
        else:
            resource_name = payload.get('resourceName') or payload.get('resource_name')
            if not resource_name:
                resource_name = f'customers/{cid}/campaignBudgets/{budget_id}'
            update_fields = {k: v for k, v in payload.items() if k not in ('resourceName', 'resource_name', 'updateMask', 'update_mask')}
            op: Dict[str, Any] = {'update': {'resourceName': resource_name, **update_fields}}
            mask = update_mask or payload.get('updateMask') or payload.get('update_mask')
            if mask:
                op['updateMask'] = mask
            elif update_fields:
                op['updateMask'] = ','.join(sorted(update_fields.keys()))
            body = {'operations': [op]}
        data, status, msg = await _gads_mutate(api, cid, 'campaignBudgets', headers, body, timeout, verify_ssl)
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
        else:
            for nested in row.values():
                if isinstance(nested, dict):
                    rn = nested.get('resourceName') or nested.get('resource_name')
                    if rn:
                        ids.append(rn)
                        break
    return ids

def _gads_provision_response(data: Any, status: int) -> Dict[str, Any]:
    records = [data] if isinstance(data, dict) else []
    provision_ids = _gads_provision_ids(data)
    return {'records': records, 'data_count': len(records), 'status': status, 'message': 'ok', 'provision_ids': provision_ids}
