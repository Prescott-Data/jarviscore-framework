ATOM_POLICY = {"effect": "destructive", "approval": "required", "idempotency_fields": ["org_id", "shift_id"], "consequence": "Deletes the scheduled shift."}

async def zoho_shifts_delete_shift(org_id: str, shift_id: str) -> dict:
    """Shifts delete shift via the zoho_shifts API."""
    try:
        resp = await nexus_call('DELETE', f'https://shifts.zoho.com/api/v1/{org_id}/shifts/{shift_id}')
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"Delete shift failed: {resp['status_code']} {resp['body']}"}
        return {'success': True, 'data': {'shift_id': shift_id, 'deleted': True}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
