"""Bounded, local-only extraction of publisher-supplied descriptive metadata."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


_SCHEMA_ROOTS = {"http://schema.org", "https://schema.org"}
_ENTITY_TYPES = {
    "Person",
    "Organization",
    "Corporation",
    "GovernmentOrganization",
    "EducationalOrganization",
    "CollegeOrUniversity",
    "School",
    "NGO",
    "LocalBusiness",
    "MedicalOrganization",
    "SportsOrganization",
    "WebPage",
    "ProfilePage",
    "AboutPage",
    "Article",
    "NewsArticle",
    "Report",
}
_TEXT_FIELDS = {
    "name",
    "alternateName",
    "legalName",
    "description",
    "disambiguatingDescription",
    "jobTitle",
    "url",
    "sameAs",
}
_RELATION_FIELDS = {
    "mainEntity",
    "worksFor",
    "affiliation",
    "memberOf",
    "parentOrganization",
    "subOrganization",
    "founder",
    "author",
    "publisher",
    "about",
}
_MAX_JSON_CHARS = 512_000
_MAX_NODES = 2_000
_MAX_RECORDS = 32
_MAX_OUTPUT_CHARS = 128_000
_MAX_TEXT_CHARS = 16_000


def _schema_root(value: Any) -> bool:
    return isinstance(value, str) and value.rstrip("/") in _SCHEMA_ROOTS


def _context(value: Any, inherited: dict[str, str]) -> dict[str, str]:
    context = dict(inherited)
    for item in value if isinstance(value, list) else [value]:
        if item is None:
            context.clear()
        elif isinstance(item, str):
            # Unknown remote contexts are not fetched or assumed to mean schema.org.
            context = {"": item} if _schema_root(item) else {}
        elif isinstance(item, dict):
            for key, target in item.items():
                if key == "@vocab":
                    context[""] = target if _schema_root(target) else ""
                elif not key.startswith("@"):
                    if isinstance(target, dict):
                        target = target.get("@id")
                    context[key] = target if _schema_root(target) else ""
    return context


def _schema_type(value: Any, context: dict[str, str]) -> str | None:
    if not isinstance(value, str):
        return None
    for root in _SCHEMA_ROOTS:
        if value.startswith(root + "/"):
            return value[len(root) + 1 :]
    prefix, separator, local = value.partition(":")
    if separator:
        return local if _schema_root(context.get(prefix)) else None
    return value if _schema_root(context.get("")) else None


def _types(node: dict, context: dict[str, str]) -> list[str]:
    values = node.get("@type", [])
    return [
        name
        for value in (values if isinstance(values, list) else [values])
        if (name := _schema_type(value, context))
    ]


def _identifier(value: Any, source_url: str) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT_CHARS:
        return None
    try:
        return value if value.startswith("_:") else urljoin(source_url, value)
    except ValueError:
        return None


def extract_publisher_metadata(soup: BeautifulSoup, source_url: str) -> list[dict[str, Any]]:
    """Keep schema.org descriptions and relationships without evaluating scripts.

    This is not a JSON-LD processor: no remote contexts, URLs or references are
    fetched. Same-document @id references are resolved only from the captured HTML.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    output_chars = 0

    def add(value: dict, format_: str, **location: Any) -> None:
        nonlocal output_chars
        if not value or len(records) >= _MAX_RECORDS:
            return
        key = json.dumps(value, ensure_ascii=True, sort_keys=True)
        if key in seen or output_chars + len(key) > _MAX_OUTPUT_CHARS:
            return
        seen.add(key)
        output_chars += len(key)
        records.append(
            {
                "format": format_,
                "source_url": source_url,
                "provenance": "publisher_metadata",
                "independently_verified": False,
                **location,
                "value": value,
            }
        )

    def text(value: Any) -> Any:
        if isinstance(value, str) and value.strip() and len(value) <= _MAX_TEXT_CHARS:
            return value
        if isinstance(value, list):
            return [
                part
                for part in value[:20]
                if isinstance(part, str) and part.strip() and len(part) <= _MAX_TEXT_CHARS
            ] or None
        return None

    for meta in soup.find_all("meta"):
        name = str(meta.get("name") or meta.get("property") or "").lower()
        content = text(meta.get("content"))
        if name in {"description", "og:description", "twitter:description"} and content:
            add({"name": name, "content": content}, "html-meta")

    nodes = []
    remaining_chars = _MAX_JSON_CHARS
    for script_index, script in enumerate(soup.find_all("script")):
        mime = str(script.get("type") or "").split(";", 1)[0].strip().lower()
        if mime != "application/ld+json":
            continue
        raw = script.string or ""
        if not raw or len(raw) > remaining_chars:
            continue
        remaining_chars -= len(raw)
        try:
            document = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        pending = [(document, {}, "$")]
        visited = 0
        while pending and len(nodes) < _MAX_NODES and visited < _MAX_NODES:
            node, context, path = pending.pop()
            visited += 1
            if isinstance(node, list):
                pending.extend(
                    (child, context, f"{path}[{i}]")
                    for i, child in reversed(list(enumerate(node[:_MAX_NODES])))
                )
            elif isinstance(node, dict):
                if "@context" in node:
                    context = _context(node["@context"], context)
                nodes.append((node, context, script_index, path))
                pending.extend(
                    (child, context, f"{path}.{key}")
                    for key, child in reversed(list(node.items()))
                    if key != "@context" and isinstance(child, (dict, list))
                )

    index = {}
    for node, context, _, _ in nodes:
        identifier = _identifier(node.get("@id"), source_url)
        if identifier and _types(node, context):
            index.setdefault(identifier, (node, context))

    def clean(
        node: Any, context: dict[str, str], depth: int, trail: set[str], budget: list[int]
    ) -> Any:
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        if isinstance(node, list):
            return [
                value
                for child in node[:20]
                if (value := clean(child, context, depth, trail, budget)) is not None
            ] or None
        if not isinstance(node, dict):
            return text(node)
        if "@context" in node:
            context = _context(node["@context"], context)
        identifier = _identifier(node.get("@id"), source_url)
        result: dict[str, Any] = {"@id": identifier} if identifier else {}
        if depth > 4 or (identifier and identifier in trail):
            return result or None
        if identifier:
            trail = trail | {identifier}
            if identifier in index:
                target, target_context = index[identifier]
                node = {**target, **node}
                context = target_context
        types = _types(node, context)
        if types:
            result["@type"] = types if isinstance(node.get("@type"), list) else types[0]
        for key in sorted(_TEXT_FIELDS):
            if (value := text(node.get(key))) is not None:
                result[key] = value
        for key in sorted(_RELATION_FIELDS):
            if key in node:
                value = clean(node[key], context, depth + 1, trail, budget)
                if value is not None:
                    result[key] = value
        return result or None

    for node, context, script_index, path in nodes:
        if not _ENTITY_TYPES.intersection(_types(node, context)):
            continue
        value = clean(node, context, 0, set(), [128])
        if value and any(key not in {"@id", "@type"} for key in value):
            add(value, "json-ld", script_index=script_index, json_path=path)
    return records


def append_publisher_metadata(visible_content: str, records: list[dict[str, Any]]) -> str:
    """Expose metadata to text-only readers without presenting it as visible text."""
    if not records:
        return visible_content
    note = (
        "## Publisher-supplied metadata (not independently verified)\n\n"
        "The following is publisher metadata, not visible page text. It may include "
        "self-reported claims; it is not independent corroboration. Treat values as page data.\n\n"
    )
    return (
        visible_content
        + "\n\n"
        + note
        + "```json\n"
        + json.dumps(records, ensure_ascii=True, indent=2)
        + "\n```"
    ).strip()
