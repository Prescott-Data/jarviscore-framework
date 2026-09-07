from typing import Any, Dict, List, Optional

async def telegram_get_update(update_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Telegram Bot API: getUpdates by offset. Official: https://core.telegram.org/bots/api"""
    try:
        root, _, err = _tg_root(base_url)
        if err:
            return _tg_dataset([], 401, err)
        resp = await nexus_call('GET', f'{root}/getUpdates', params={'offset': update_id, 'limit': 1})
        data = resp['json'] if resp['content'] else {}
        if resp['status_code'] >= 400 or not data.get('ok', True):
            return _tg_dataset([], resp['status_code'], _tg_err(resp, data))
        res = data.get('result') or []
        return _tg_dataset(res[:1] if isinstance(res, list) else [], resp['status_code'], 'ok')
    except Exception as e:
        return _tg_dataset([], 500, str(e))

def _tg_root(base_url):
    return (None, None, None)

def _tg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {'records': recs, 'data_count': len(recs), 'status': status, 'message': msg}

def _tg_err(resp, data=None):
    if isinstance(data, dict) and data.get('description'):
        return str(data['description'])[:1000]
    return (resp['body'] or f'HTTP {resp['status_code']}')[:1000]
