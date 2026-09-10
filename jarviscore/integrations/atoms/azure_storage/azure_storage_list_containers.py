async def azure_storage_list_containers(account_name: str) -> dict:
    """Storage list containers via the azure_storage API."""
    import xml.etree.ElementTree as ET
    try:
        resp = await nexus_call('GET', f'https://{account_name}.blob.core.windows.net/', headers={'x-ms-version': '2020-10-02'}, params={'comp': 'list'})
        if resp['status_code'] != 200:
            return {'success': False, 'data': None, 'error': f"List containers failed: {resp['status_code']} {resp['body']}"}
        root = ET.fromstring(resp['body'])
        containers = [c.find('Name').text for c in root.findall('.//Container')]
        return {'success': True, 'data': {'containers': containers, 'count': len(containers)}, 'error': None}
    except Exception as e:
        return {'success': False, 'data': None, 'error': str(e)}
