async def google_drive_get_document(document_id: str, tab: str = "") -> dict:
    """Read a Google Docs document, a tab at a time.

    With no ``tab`` the first tab's text comes back with a list of every tab and its
    size, so a long document (meeting notes with a transcript tab) is read where it
    starts and the rest is known to be there. ``tab`` names another by its title or
    id; ``tab="all"`` gives every tab, each under its title. Tables are read.
    """
    resp = await nexus_call(
        'GET',
        f'https://docs.googleapis.com/v1/documents/{document_id}',
        provider='google_drive',
        # Asked without this, the Docs API answers with the first tab alone and says
        # nothing of the others: meeting notes came back without their transcript tab.
        params={'includeTabsContent': 'true'},
    )
    if not resp['ok']:
        return {
            'success': False,
            'document_id': document_id,
            'title': None,
            'text': None,
            'paragraph_count': 0,
            'content_length': 0,
            'tabs': [],
            'error': resp['body'],
        }
    document = resp['json'] or {}
    paragraphs = [0]

    def element_text(element):
        run = element.get('textRun')
        if isinstance(run, dict):
            return str(run.get('content') or '')
        # Smart chips carry what a reader sees in place of text: a linked file, a person.
        link = (element.get('richLink') or {}).get('richLinkProperties') or {}
        if link:
            return str(link.get('title') or link.get('uri') or '')
        person = (element.get('person') or {}).get('personProperties') or {}
        if person:
            return str(person.get('name') or person.get('email') or '')
        return ''

    def content_text(content):
        parts = []
        for item in content or []:
            paragraph = item.get('paragraph')
            if isinstance(paragraph, dict):
                paragraphs[0] += 1
                parts.append(''.join(
                    element_text(element) for element in paragraph.get('elements', [])
                ))
                continue
            table = item.get('table')
            if isinstance(table, dict):
                for row in table.get('tableRows', []):
                    for cell in row.get('tableCells', []):
                        parts.append(content_text(cell.get('content')))
                continue
            contents = item.get('tableOfContents')
            if isinstance(contents, dict):
                parts.append(content_text(contents.get('content')))
        return ''.join(parts)

    def walk(tabs, found):
        for tab in tabs or []:
            properties = tab.get('tabProperties') or {}
            body = (tab.get('documentTab') or {}).get('body') or {}
            found.append({
                'id': properties.get('tabId'),
                'title': properties.get('title'),
                'text': content_text(body.get('content')),
            })
            walk(tab.get('childTabs'), found)
        return found

    tabs = walk(document.get('tabs'), [])
    if not tabs:
        # An answer without tabs carries the document's one body at the top.
        tabs = [{
            'id': None,
            'title': None,
            'text': content_text((document.get('body') or {}).get('content')),
        }]
    listed = [
        {'id': each['id'], 'title': each['title'], 'content_length': len(each['text'].strip())}
        for each in tabs
    ]
    wanted = str(tab or '').strip()
    note = None
    if wanted.lower() == 'all' and len(tabs) > 1:
        text = '\n'.join(
            f"===== Tab: {each['title'] or each['id']} =====\n{each['text']}" for each in tabs
        )
    elif wanted and wanted.lower() != 'all':
        match = [
            each for each in tabs
            if wanted.lower() in (str(each['id'] or '').lower(), str(each['title'] or '').lower())
        ]
        if not match:
            return {
                'success': False,
                'document_id': document_id,
                'title': document.get('title'),
                'text': None,
                'paragraph_count': 0,
                'content_length': 0,
                'tabs': listed,
                'error': f"No tab named {wanted!r}. Tabs: "
                         + ', '.join(repr(each['title'] or each['id']) for each in tabs),
            }
        text = match[0]['text']
    else:
        text = tabs[0]['text']
        if len(tabs) > 1:
            others = ', '.join(
                f"{each['title'] or each['id']!r} ({each['content_length']} characters)"
                for each in listed[1:]
            )
            note = (
                f"This is the first of {len(tabs)} tabs, {tabs[0]['title'] or tabs[0]['id']!r}. "
                f"Not included: {others}. Pass tab=<title> for one of them, or tab='all'."
            )
    return {
        'success': True,
        'document_id': document_id,
        'title': document.get('title'),
        'text': text,
        'paragraph_count': paragraphs[0],
        'content_length': len(text.strip()),
        'tabs': listed,
        **({'note': note} if note else {}),
        'error': None,
    }
