"""
MkDocs hook: embed_markdown
============================
Embeds the raw markdown source of each page into the rendered HTML as a
<script type="text/markdown" id="jc-page-source"> block.

The llm-assist.js widget reads this directly — no fetch needed, no CORS
issues, works identically on localhost and production.
"""
import ast
import html
from collections import defaultdict
from pathlib import Path


CATALOG_MARKER = "<!-- GENERATED_ATOM_CATALOG -->"


def _provider_metadata(repo_root: Path) -> dict:
    source = (
        repo_root / "jarviscore" / "integrations" / "seed_registry.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "PROVIDER_META":
            return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "PROVIDER_META" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError("PROVIDER_META was not found in seed_registry.py")


def _render_atom_catalog(config) -> str:
    repo_root = Path(config.config_file_path).resolve().parent
    atoms_root = repo_root / "jarviscore" / "integrations" / "atoms"
    providers = _provider_metadata(repo_root)
    by_category = defaultdict(list)
    total_atoms = 0

    for system, metadata in providers.items():
        atom_dir = atoms_root / system
        atom_count = len([
            path for path in atom_dir.glob("*.py")
            if not path.name.startswith("__")
        ]) if atom_dir.is_dir() else 0
        total_atoms += atom_count
        by_category[metadata["category"]].append({
            "system": system,
            "auth_type": metadata["auth_type"],
            "status": metadata["status"],
            "capabilities": metadata["capabilities"],
            "atom_count": atom_count,
        })

    lines = [
        f"**{len(providers)} bundles · {total_atoms} atoms in this source tree**",
        "",
        "This directory is generated at build time from `PROVIDER_META` and the",
        "atom files on disk. Use `jarviscore atom list --bundle <name>` for the",
        "exact atom names shipped in your installed version.",
        "",
    ]
    for category in sorted(by_category):
        title = category.replace("_", " ").replace("&", "and").title()
        lines.extend([
            f"### {title}",
            "",
            "| Bundle | Auth | Seed stage | Atoms | Capabilities |",
            "|---|---|---|---:|---|",
        ])
        for item in sorted(by_category[category], key=lambda value: value["system"]):
            capabilities = ", ".join(
                f"`{capability}`" for capability in item["capabilities"]
            )
            lines.append(
                f"| `{item['system']}` | `{item['auth_type']}` | "
                f"`{item['status']}` | {item['atom_count']} | {capabilities} |"
            )
        lines.append("")
    return "\n".join(lines)


def on_page_markdown(markdown: str, page, config, files, **kwargs) -> str:
    """Expand source-backed documentation fragments before rendering."""
    if page.file.src_uri == "guides/integrations.md":
        if CATALOG_MARKER not in markdown:
            raise RuntimeError("Integrations guide is missing its generated catalog marker")
        return markdown.replace(CATALOG_MARKER, _render_atom_catalog(config))
    return markdown


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
