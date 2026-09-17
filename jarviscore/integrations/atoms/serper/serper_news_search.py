async def serper_news_search(query: str, num: int=10, tbs: str=None) -> dict:
    """News search. POST https://google.serper.dev/news"""
    _h = {'Content-Type': 'application/json'}
    payload = {'q': query, 'num': num, 'type': 'news'}
    if tbs:
        payload['tbs'] = tbs
    resp = await nexus_call('POST', 'https://google.serper.dev/news', headers=_h, json=payload)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    news = [{'title': n.get('title'), 'link': n.get('link'), 'snippet': n.get('snippet'), 'source': n.get('source'), 'date': n.get('date')} for n in data.get('news', [])]
    return {'success': True, 'query': query, 'news': news, 'count': len(news)}
