ATOM_POLICY = {"effect": "destructive", "approval": "required", "idempotency_fields": ["event_id"], "consequence": "Deletes the Microsoft calendar event."}

async def msgraph_delete_event(event_id: str) -> dict:
    """Delete event via the msgraph API."""
    try:
        resp = await nexus_call('DELETE', f'https://graph.microsoft.com/v1.0/me/events/{event_id}')
        if resp['status_code'] != 204:
            return {'success': False, 'data': None, 'error': f"Delete event failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': {'event_id': event_id, 'deleted': True}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
