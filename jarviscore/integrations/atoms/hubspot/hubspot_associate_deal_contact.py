ATOM_POLICY = {
    'effect': 'write',
    'approval': 'never',
    'idempotency_fields': ['deal_id', 'contact_id'],
    'consequence': 'Associates one existing HubSpot deal with one existing contact.',
}


async def hubspot_associate_deal_contact(deal_id: str, contact_id: str) -> dict:
    """Associate a HubSpot deal with a contact and verify the association."""
    associated = await nexus_call(
        'PUT',
        f'https://api.hubapi.com/crm/v4/objects/deals/{deal_id}/associations/default/contacts/{contact_id}',
        provider='hubspot',
    )
    if not associated['ok']:
        return {
            'success': False,
            'deal_id': deal_id,
            'contact_id': contact_id,
            'association_verified': False,
            'error': associated['body'],
        }
    verified = await nexus_call(
        'GET',
        f'https://api.hubapi.com/crm/v4/objects/contacts/{contact_id}/associations/deals',
        provider='hubspot',
        params={'limit': 100},
    )
    if not verified['ok']:
        return {
            'success': False,
            'deal_id': deal_id,
            'contact_id': contact_id,
            'association_verified': False,
            'error': verified['body'],
        }
    matches = [
        str(item.get('toObjectId'))
        for item in verified['json'].get('results', [])
    ]
    association_verified = str(deal_id) in matches
    return {
        'success': association_verified,
        'deal_id': deal_id,
        'contact_id': contact_id,
        'association_verified': association_verified,
        'error': None if association_verified else 'Association was not present on readback.',
    }