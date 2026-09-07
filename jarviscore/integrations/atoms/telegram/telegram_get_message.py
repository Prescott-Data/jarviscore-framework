from typing import Any, Dict, List, Optional

async def telegram_get_message(chat_id: str, message_id: str, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """Telegram Bot API: getChat. Official: https://core.telegram.org/bots/api"""
    try:
        root, _, err = _tg_root(base_url)
        if err:
            return _tg_dataset([], 401, err)
        if not chat_id:
            return _tg_dataset([], 400, 'chat_id is required')
        resp = await nexus_call('GET', f'{root}/getChat', params={'chat_id': chat_id})
        data = resp['json'] if resp['content'] else {}
        if resp['status_code'] >= 400 or not data.get('ok', True):
            return _tg_dataset([], resp['status_code'], _tg_err(resp, data))
        res = data.get('result')
        return _tg_dataset([res] if isinstance(res, dict) else [], resp['status_code'], 'ok')
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
