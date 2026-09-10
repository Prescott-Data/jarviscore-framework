ATOM_POLICY = {
    "effect": "notify",
    "approval": "never",
    "idempotency_fields": ["channel", "text"],
    "consequence": "Posts one message to the selected Slack channel.",
}


async def slack_send_message(channel: str, text: str, thread_ts: str=None) -> dict:
    """Send message via the slack API."""
    _base = 'https://slack.com/api'
    _h = {'Content-Type': 'application/json'}

    async def _get(p, params=None, headers=None):
        _r = await nexus_call('GET', f'{_base}{p}', headers={**_h, **(headers or {})}, params=params or {})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _post(p, data=None, headers=None):
        _r = await nexus_call('POST', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _put(p, data=None, headers=None):
        _r = await nexus_call('PUT', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _patch(p, data=None, headers=None):
        _r = await nexus_call('PATCH', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}

    async def _delete(p, headers=None):
        _r = await nexus_call('DELETE', f'{_base}{p}', headers={**_h, **(headers or {})})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}
    payload = {'channel': channel, 'text': text}
    if thread_ts:
        payload['thread_ts'] = thread_ts
    resp = await _post('/chat.postMessage', data=payload)
    if not resp.get('ok'):
        raise RuntimeError(resp.get('error', 'Slack API error'))
    return {'ts': resp['ts'], 'channel': resp['channel'], 'text': text}
