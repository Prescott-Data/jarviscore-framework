async def hubspot_create_deal(deal_name: str, stage: str, amount: float=None, pipeline: str='default', close_date: str=None) -> dict:
    """Create deal. POST https://api.hubapi.com/crm/v3/objects/deals"""
    _h = {'Content-Type': 'application/json'}
    props = {'dealname': deal_name, 'dealstage': stage, 'pipeline': pipeline}
    if amount is not None:
        props['amount'] = str(amount)
    if close_date:
        props['closedate'] = close_date
    resp = await nexus_call('POST', 'https://api.hubapi.com/crm/v3/objects/deals', headers=_h, json={'properties': props})
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    return {'success': True, 'id': data.get('id'), 'deal_name': deal_name, 'stage': stage}
