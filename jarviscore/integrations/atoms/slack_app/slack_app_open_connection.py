ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
    "idempotency_fields": [],
    "consequence": "Opens a Socket Mode connection; Slack then sends the app's events over it.",
}


async def slack_app_open_connection() -> dict:
    """Open a Slack Socket Mode connection with the app-level token; returns its websocket URL."""
    _r = await nexus_call('POST', 'https://slack.com/api/apps.connections.open',
                          headers={'Content-Type': 'application/x-www-form-urlencoded'})
    if not _r['ok']:
        raise RuntimeError(_r['body'])
    resp = _r['json'] or {}
    if not resp.get('ok'):
        raise RuntimeError(resp.get('error', 'Slack API error'))
    return {'url': resp['url']}
