async def gmail_list_messages(query: str='', max_results: int=20) -> dict:
    """List messages via the gmail API."""
    _base = 'https://gmail.googleapis.com/gmail/v1/users/me'
    _h = {}
    params = {'maxResults': max_results}
    if query:
        params['q'] = query
    resp = await nexus_call('GET', f'{_base}/messages', headers=_h, params=params)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'messages': data.get('messages', []), 'result_size_estimate': data.get('resultSizeEstimate', 0)}
