from typing import Any, Dict, List, Optional
INTERCOM_API = 'https://api.intercom.io'

async def intercom_search_records(query: str, limit: int=25, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Search Intercom contacts via POST /contacts/search. Official: https://developers.intercom.com/docs/references/rest-api/api.intercom.io/contacts/searchcontacts"""
    try:
        if not query:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'query is required'}
        api, err = _ic_api_root(base_url)
        if err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': err}
        headers, auth_err = _ic_auth(json_body=True)
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        body = {'query': {'operator': 'OR', 'value': [{'field': 'email', 'operator': '~', 'value': query}, {'field': 'name', 'operator': '~', 'value': query}]}, 'pagination': {'per_page': min(max(int(limit or 25), 1), 150)}}
        resp = await _ic_post(f'{api}/contacts/search', headers, body, timeout, verify_ssl)
        if resp['status_code'] >= 400:
            return {'records': [], 'data_count': 0, 'status': resp['status_code'], 'message': resp['body'][:1000]}
        data = resp['json'] if resp['body'] else {}
        batch = data.get('data') if isinstance(data, dict) else []
        records = [item for item in batch or [] if isinstance(item, dict)][:limit]
        return {'records': records, 'data_count': len(records), 'status': resp['status_code'], 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _ic_api_root(base_url):
    root = (base_url or INTERCOM_API).rstrip('/')
    if 'intercom.io' not in root:
        return (None, 'base_url must be https://api.intercom.io')
    return (root, None)

def _ic_auth(json_body=False):
    headers = {'Accept': 'application/json', 'Intercom-Version': '2.11'}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return (headers, None)

async def _ic_post(url, headers, body, timeout, verify_ssl):
    return await nexus_call('POST', url, headers=headers, json=body)
