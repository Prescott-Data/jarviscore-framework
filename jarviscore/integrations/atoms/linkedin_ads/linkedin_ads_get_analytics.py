async def linkedin_ads_get_analytics(account_id: str, start_year: int, start_month: int, start_day: int, end_year: int, end_month: int, end_day: int, pivot: str='CAMPAIGN') -> list:
    """Ads get analytics via the linkedin_ads API."""
    _base = 'https://api.linkedin.com/v2'
    _h = {'Content-Type': 'application/json'}

    async def _get(p, params=None, headers=None):
        _r = await nexus_call('GET', f'{_base}{p}', headers={**_h, **(headers or {})}, params=params or {})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _post(p, data=None, headers=None):
        _r = await nexus_call('POST', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _put(p, data=None, headers=None):
        _r = await nexus_call('PUT', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json']

    async def _patch(p, data=None, headers=None):
        _r = await nexus_call('PATCH', f'{_base}{p}', headers={**_h, **(headers or {})}, json=data)
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}

    async def _delete(p, headers=None):
        _r = await nexus_call('DELETE', f'{_base}{p}', headers={**_h, **(headers or {})})
        if not _r['ok']:
            return {'success': False, 'error': _r['body']}
        return _r['json'] if _r['content'] else {}
    account_urn = f'urn:li:sponsoredAccount:{account_id}'
    resp = await _get('/adAnalyticsV2', params={'q': 'analytics', 'pivot': pivot, 'dateRange.start.year': start_year, 'dateRange.start.month': start_month, 'dateRange.start.day': start_day, 'dateRange.end.year': end_year, 'dateRange.end.month': end_month, 'dateRange.end.day': end_day, 'accounts': f'List({account_urn})', 'fields': 'impressions,clicks,costInLocalCurrency,totalEngagements,pivotValue'})
    return [{'pivot_value': r.get('pivotValue'), 'impressions': r.get('impressions'), 'clicks': r.get('clicks'), 'cost': r.get('costInLocalCurrency'), 'total_engagements': r.get('totalEngagements'), 'date_range': r.get('dateRange')} for r in resp.get('elements', [])]
