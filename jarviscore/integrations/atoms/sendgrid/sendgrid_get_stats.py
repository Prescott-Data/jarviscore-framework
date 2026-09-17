async def sendgrid_get_stats(start_date: str, end_date: str=None) -> dict:
    """Get stats. GET https://api.sendgrid.com/v3/stats"""
    _h = {}
    params = {'start_date': start_date, 'aggregated_by': 'day'}
    if end_date:
        params['end_date'] = end_date
    resp = await nexus_call('GET', 'https://api.sendgrid.com/v3/stats', headers=_h, params=params)
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    return {'success': True, 'stats': resp['json']}
