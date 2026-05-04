"""
MkDocs hook: embed_markdown
============================
Embeds the raw markdown source of each page into the rendered HTML as a
<script type="text/markdown" id="jc-page-source"> block.

The llm-assist.js widget reads this directly — no fetch needed, no CORS
issues, works identically on localhost and production.
"""
import html


def on_page_content(html_content: str, page, config, files, **kwargs) -> str:
    """Inject the raw markdown source into every rendered page."""
    raw_md = page.markdown or ""
    # Escape for safe embedding inside a script tag
    escaped = html.escape(raw_md, quote=False)
    injection = (
        f'\n<script type="text/markdown" id="jc-page-source">'
        f'{escaped}'
        f'</script>\n'
    )
    return html_content + injection
