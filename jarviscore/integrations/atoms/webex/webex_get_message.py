async def webex_get_message(message_id: str) -> dict:
    """Get message via the webex API."""
    try:
        resp = await nexus_call('GET', f'https://webexapis.com/v1/messages/{message_id}')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Get message failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
