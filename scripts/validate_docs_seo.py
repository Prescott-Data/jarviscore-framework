#!/usr/bin/env python3
"""Validate source and rendered SEO contracts for the documentation site."""

from __future__ import annotations

import ast
import json
import re
import struct
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "jarviscore" / "docs"
SITE_DIR = ROOT / "site"
SITE_URL = "https://jarviscore.developers.prescottdata.io/"
SOCIAL_IMAGE_URL = f"{SITE_URL}assets/social-card.png"
MERMAID_SCRIPT = "https://cdn.jsdelivr.net/npm/mermaid@11.12.2/dist/mermaid.min.js"
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)


class HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.canonicals: list[str] = []
        self.json_ld: list[str] = []
        self._json_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "meta":
            name = values.get("name") or values.get("property")
            if name:
                self.meta[name] = values.get("content", "")
        elif tag == "link" and values.get("rel") == "canonical":
            self.canonicals.append(values.get("href", ""))
        elif tag == "script" and values.get("type") == "application/ld+json":
            self._json_parts = []

    def handle_data(self, data: str) -> None:
        if self._json_parts is not None:
            self._json_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json_parts is not None:
            self.json_ld.append("".join(self._json_parts))
            self._json_parts = None


def front_matter_value(block: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", block)
    if not match:
        return ""
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def schema_types(value: object) -> set[str]:
    if isinstance(value, list):
        return set().union(*(schema_types(item) for item in value))
    if not isinstance(value, dict):
        return set()
    types = schema_types(value.get("@graph", []))
    item_type = value.get("@type")
    if isinstance(item_type, str):
        types.add(item_type)
    elif isinstance(item_type, list):
        types.update(item for item in item_type if isinstance(item, str))
    return types


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    return struct.unpack(">II", data[16:24])


def provider_metadata() -> dict:
    source = (
        ROOT / "jarviscore" / "integrations" / "seed_registry.py"
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


def validate_sources(errors: list[str]) -> int:
    titles: list[str] = []
    descriptions: list[str] = []
    pages = sorted(DOCS_DIR.rglob("*.md"))
    for path in pages:
        relative = path.relative_to(ROOT)
        match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
        if not match:
            errors.append(f"{relative}: missing YAML front matter")
            continue
        title = front_matter_value(match.group(1), "title")
        description = front_matter_value(match.group(1), "description")
        if not 20 <= len(title) <= 65:
            errors.append(f"{relative}: title length is {len(title)}, expected 20-65")
        if not 100 <= len(description) <= 165:
            errors.append(
                f"{relative}: description length is {len(description)}, expected 100-165"
            )
        titles.append(title.casefold())
        descriptions.append(description.casefold())

    for label, values in (("title", titles), ("description", descriptions)):
        for value, count in Counter(values).items():
            if value and count > 1:
                errors.append(f"duplicate {label}: {value!r}")
    return len(pages)


def validate_rendered(errors: list[str]) -> int:
    required_meta = {
        "description",
        "og:title",
        "og:description",
        "og:url",
        "og:image",
        "twitter:card",
        "twitter:title",
        "twitter:description",
        "twitter:image",
    }
    base_schema = {"Organization", "SoftwareApplication", "WebSite"}
    pages = sorted(SITE_DIR.glob("**/index.html"))
    for path in pages:
        relative = path.relative_to(SITE_DIR)
        html = path.read_text(encoding="utf-8")
        parser = HeadParser()
        parser.feed(html)
        if len(parser.canonicals) != 1 or not parser.canonicals[0]:
            errors.append(f"{relative}: expected exactly one canonical URL")
        missing = sorted(key for key in required_meta if not parser.meta.get(key))
        if missing:
            errors.append(f"{relative}: missing metadata {', '.join(missing)}")
        if parser.meta.get("og:image") != SOCIAL_IMAGE_URL:
            errors.append(f"{relative}: incorrect og:image")
        if parser.meta.get("twitter:image") != SOCIAL_IMAGE_URL:
            errors.append(f"{relative}: incorrect twitter:image")
        if parser.meta.get("twitter:card") != "summary_large_image":
            errors.append(f"{relative}: incorrect twitter:card")
        if len(parser.json_ld) != 1:
            errors.append(f"{relative}: expected exactly one JSON-LD block")
            continue
        try:
            data = json.loads(parser.json_ld[0])
        except json.JSONDecodeError as exc:
            errors.append(f"{relative}: invalid JSON-LD: {exc}")
            continue
        required_schema = set(base_schema)
        if relative != Path("index.html"):
            required_schema.update({"TechArticle", "BreadcrumbList"})
        missing_schema = sorted(required_schema - schema_types(data))
        if missing_schema:
            errors.append(f"{relative}: missing schema types {', '.join(missing_schema)}")
        if 'class="mermaid-source"' in html:
            if MERMAID_SCRIPT not in html:
                errors.append(f"{relative}: missing pinned Mermaid runtime")
            if "javascripts/mermaid-render.js" not in html:
                errors.append(f"{relative}: missing Mermaid renderer")
    return len(pages)


def validate_static_files(errors: list[str]) -> None:
    robots = SITE_DIR / "robots.txt"
    expected_sitemap = f"Sitemap: {SITE_URL}sitemap.xml"
    if not robots.exists() or expected_sitemap not in robots.read_text(encoding="utf-8"):
        errors.append("robots.txt does not advertise the canonical sitemap")
    if not (SITE_DIR / "sitemap.xml").exists():
        errors.append("sitemap.xml is missing")
    image = SITE_DIR / "assets" / "social-card.png"
    try:
        dimensions = png_dimensions(image)
    except (OSError, ValueError) as exc:
        errors.append(f"social-card.png is invalid: {exc}")
    else:
        if dimensions != (1200, 630):
            errors.append(f"social-card.png is {dimensions}, expected (1200, 630)")

    source_diagrams = sum(
        path.read_text(encoding="utf-8").count("```mermaid")
        for path in DOCS_DIR.rglob("*.md")
    )
    rendered_diagrams = sum(
        path.read_text(encoding="utf-8").count('class="mermaid-source"')
        for path in SITE_DIR.glob("**/index.html")
    )
    if source_diagrams != rendered_diagrams:
        errors.append(
            f"Mermaid source/rendered count differs: {source_diagrams} Markdown, "
            f"{rendered_diagrams} rendered"
        )

    catalog_source = DOCS_DIR / "guides" / "integrations.md"
    catalog_html = SITE_DIR / "guides" / "integrations" / "index.html"
    marker = "<!-- GENERATED_ATOM_CATALOG -->"
    if marker not in catalog_source.read_text(encoding="utf-8"):
        errors.append("integrations.md is missing the generated catalog marker")
    rendered_catalog = catalog_html.read_text(encoding="utf-8")
    if marker in rendered_catalog:
        errors.append("generated integrations catalog marker leaked into HTML")
    providers = provider_metadata()
    atoms_root = ROOT / "jarviscore" / "integrations" / "atoms"
    atom_count = sum(
        1 for path in atoms_root.glob("*/*.py") if not path.name.startswith("__")
    )
    expected_summary = f"{len(providers)} bundles · {atom_count} atoms"
    if expected_summary not in rendered_catalog:
        errors.append(
            f"integrations catalog summary does not contain {expected_summary!r}"
        )
    for system in providers:
        if f"<code>{system}</code>" not in rendered_catalog:
            errors.append(f"integrations catalog is missing provider {system!r}")


def main() -> int:
    errors: list[str] = []
    source_count = validate_sources(errors)
    rendered_count = validate_rendered(errors)
    validate_static_files(errors)
    if source_count != rendered_count:
        errors.append(
            f"source/rendered page count differs: {source_count} Markdown, "
            f"{rendered_count} rendered"
        )
    if errors:
        print("SEO validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"SEO validation passed for {source_count} documentation pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())