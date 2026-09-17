async def serper_search(query: str, num: int=10, gl: str='ke', hl: str='en') -> dict:
    """Search. POST https://google.serper.dev/search"""
    _h = {'Content-Type': 'application/json'}
    payload = {'q': query, 'num': num, 'gl': gl, 'hl': hl}
    resp = await nexus_call('POST', 'https://google.serper.dev/search', headers=_h, json=payload)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    results = [{'title': r.get('title'), 'link': r.get('link'), 'snippet': r.get('snippet'), 'position': r.get('position')} for r in data.get('organic', [])]
    return {'success': True, 'query': query, 'results': results, 'answer_box': data.get('answerBox'), 'knowledge_graph': data.get('knowledgeGraph')}
