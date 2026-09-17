ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["deal_name", "stage", "pipeline", "contact_id"],
    "consequence": "Creates one HubSpot deal when no matching deal exists.",
}


async def hubspot_create_deal(deal_name: str, stage: str, amount: float=None, pipeline: str='default', close_date: str=None, contact_id: str=None) -> dict:
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
    deal_id = data.get('id')
    association_verified = None
    association_error = None
    if contact_id and deal_id:
        associated = await nexus_call(
            'PUT',
            f'https://api.hubapi.com/crm/v4/objects/deals/{deal_id}/associations/default/contacts/{contact_id}',
            provider='hubspot',
        )
        if associated['ok']:
            verified = await nexus_call(
                'GET',
                f'https://api.hubapi.com/crm/v4/objects/contacts/{contact_id}/associations/deals',
                provider='hubspot',
                params={'limit': 100},
            )
            if verified['ok']:
                association_verified = str(deal_id) in {
                    str(item.get('toObjectId'))
                    for item in verified['json'].get('results', [])
                }
                if not association_verified:
                    association_error = 'Association was not present on readback.'
            else:
                association_verified = False
                association_error = verified['body']
        else:
            association_verified = False
            association_error = associated['body']
    return {
        'success': True,
        'id': deal_id,
        'deal_name': deal_name,
        'stage': stage,
        'contact_id': contact_id,
        'association_verified': association_verified,
        'association_error': association_error,
    }
