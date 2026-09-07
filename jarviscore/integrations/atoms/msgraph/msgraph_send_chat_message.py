async def msgraph_send_chat_message(chat_id: str, message: str) -> dict:
    """Send chat message via the msgraph API."""
    try:
        access_token = _get_nexus_token(None)
    except Exception as e:
        return {'success': False, 'data': None, 'error': f'Auth error: {str(e)}'}
    try:
        resp = await nexus_call('POST', f'https://graph.microsoft.com/v1.0/me/chats/{chat_id}/messages', headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}, json={'body': {'content': message}})
        if resp['status_code'] != 201:
            return {'success': False, 'data': None, 'error': f"Send chat message failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': resp['json'], 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
