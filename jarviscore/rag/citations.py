"""Exact, source-located citation atoms carried by RAG results."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


def validate_citation_atoms(
    content: str, citation_atoms: Any
) -> list[dict[str, Any]]:
    """Validate opaque citation atoms without interpreting their source locators."""
    if citation_atoms is None:
        return []
    if not isinstance(citation_atoms, list):
        raise TypeError("citation_atoms must be a list")
    validated = []
    for atom in citation_atoms:
        if not isinstance(atom, dict):
            raise TypeError("each citation atom must be an object")
        quote = atom.get("quote")
        locator = atom.get("locator")
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("each citation atom requires a nonempty quote")
        if quote not in content:
            raise ValueError("each citation atom quote must appear in document content")
        if not isinstance(locator, dict) or not locator:
            raise ValueError("each citation atom requires a source locator")
        try:
            json.dumps(atom, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("citation atoms must be JSON-safe") from error
        validated.append(deepcopy(atom))
    return validated


def citation_atoms_for_chunk(
    chunk: str, citation_atoms: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return only exact atoms whose complete quote survives in this chunk."""
    return [deepcopy(atom) for atom in citation_atoms if atom["quote"] in chunk]