async def gmail_get_message(message_id: str) -> dict:
    """Get one Gmail message: its headers, its text and the links in it.

    The text is the plain part when the message has one, wherever it sits in the
    message (a message with an attachment nests its text one level down). A message
    sent as HTML only is returned as the text of its HTML. `links` are the web
    addresses in the HTML part with the words they are under, which the plain part
    of many messages leaves out. Official:
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get
    """
    import base64
    from html.parser import HTMLParser

    _base = 'https://gmail.googleapis.com/gmail/v1/users/me'
    resp = await nexus_call('GET', f'{_base}/messages/{message_id}', headers={}, params={'format': 'full'})
    if not resp['ok']:
        return {'success': False, 'error': resp['body']}
    data = resp['json']
    payload = data.get('payload') or {}
    headers = {h['name']: h['value'] for h in payload.get('headers', [])}

    found = {'text/plain': [], 'text/html': []}
    attachments = []
    stack = [payload]
    while stack:
        part = stack.pop(0)
        stack[0:0] = part.get('parts') or []
        kind = (part.get('mimeType') or '').lower()
        if part.get('filename'):
            attachments.append(part['filename'])
            continue
        raw = (part.get('body') or {}).get('data') or ''
        if kind in found and raw:
            found[kind].append(base64.urlsafe_b64decode(raw + '==').decode('utf-8', errors='ignore'))

    class _Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.out, self.links, self.skip, self.href, self.words = [], [], 0, None, []

        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style', 'head'):
                self.skip += 1
            elif tag in ('br', 'p', 'div', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'table'):
                self.out.append('\n')
            if tag == 'a':
                self.href, self.words = dict(attrs).get('href'), []

        def handle_endtag(self, tag):
            if tag in ('script', 'style', 'head'):
                self.skip = max(0, self.skip - 1)
            elif tag in ('p', 'div', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'td'):
                self.out.append('\n' if tag != 'td' else ' ')
            if tag == 'a' and self.href:
                if self.href.startswith(('http://', 'https://', 'mailto:')):
                    self.links.append({'text': ' '.join(' '.join(self.words).split())[:200], 'url': self.href})
                self.href = None

        def handle_data(self, text):
            if self.skip:
                return
            self.out.append(text)
            if self.href:
                self.words.append(text)

    html = '\n'.join(found['text/html'])
    reader = _Text()
    if html:
        reader.feed(html)
    body = '\n'.join(found['text/plain'])
    if not body.strip() and html:
        lines = [' '.join(line.split()) for line in ''.join(reader.out).splitlines()]
        body = '\n'.join(line for i, line in enumerate(lines) if line or (i and lines[i - 1]))
    links, seen = [], set()
    for link in reader.links:
        if link['url'] not in seen:
            seen.add(link['url'])
            links.append(link)
    return {'success': True, 'id': message_id, 'subject': headers.get('Subject'), 'from': headers.get('From'),
            'to': headers.get('To'), 'date': headers.get('Date'), 'body': body, 'links': links[:100],
            'attachments': attachments}
