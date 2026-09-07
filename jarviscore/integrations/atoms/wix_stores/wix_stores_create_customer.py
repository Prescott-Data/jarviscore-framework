from typing import Any, Dict, List, Optional
WIX_API = 'https://www.wixapis.com'

async def wix_stores_create_customer(email: str, site_id: str='', first_name: str='', last_name: str='', phone: str='', timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """wix_stores API: create customer. Official: https://dev.wix.com/docs/rest/business-solutions/stores"""
    try:
        if not email:
            return _wx_provision({}, 400, 'email is required')
        root, err = _wx_root(base_url)
        if err:
            return _wx_provision({}, 400, err)
        headers, aerr = _wx_headers(site_id)
        if aerr:
            return _wx_provision({}, 401, aerr)
        info: Dict[str, Any] = {'emails': {'items': [{'email': email, 'primary': True}]}}
        if first_name or last_name:
            info['name'] = {'first': first_name, 'last': last_name}
        if phone:
            info['phones'] = {'items': [{'phone': phone, 'primary': True}]}
        resp = await nexus_call('POST', f'{root}/contacts/v4/contacts', headers=headers, json={'info': info})
        if resp['status_code'] >= 400:
            return _wx_provision({}, resp['status_code'], _wx_err(resp))
        return _wx_provision(resp['json'] if resp['content'] else {}, resp['status_code'], 'ok', key='contact')
    except Exception as e:
        return _wx_provision({}, 500, str(e))

def _wx_root(base_url):
    raw = (base_url or None or WIX_API).strip().rstrip('/')
    if 'wixapis.com' not in raw:
        return (None, 'base_url must be https://www.wixapis.com')
    return (raw[:raw.index('wixapis.com') + len('wixapis.com')], None)

def _wx_headers(site_id):
    sid = site_id or None
    if not sid:
        return (None, 'site_id is required (wix-site-id header for site-level calls)')
    return ({'wix-site-id': str(sid), 'Content-Type': 'application/json', 'Accept': 'application/json'}, None)

def _wx_provision(data, status, msg, key=None, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get(key) if key and isinstance(obj.get(key), dict) else obj
    pid = inner.get('id') or inner.get('_id') or fallback_id
    ids = [pid] if pid not in (None, '') else []
    rec = inner if inner else {'id': pid} if ids else {}
    return {'records': [rec] if rec else [], 'data_count': 1 if rec else 0, 'status': status, 'message': msg, 'provision_ids': ids}

def _wx_err(resp):
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
