"""
Context Distillation for JarvisCore v1.0.1.

Converts raw agent outputs into structured TruthFacts, scrubs
sensitive data, and merges new facts into existing TruthContext.

Three functions:
- distill_output: Raw output → Dict[str, TruthFact]
- scrub_sensitive: Remove passwords, tokens, keys from dicts
- merge_facts: Incorporate new facts into TruthContext with versioning

Ported from IA/CA patterns with improvements:
- Explicit sensitive key list (not regex guessing)
- Deep recursive scrubbing (nested dicts and lists)
- Version bumping on merge (conflict detection)
- History ledger tracks every mutation
"""

import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .truth import Evidence, TruthContext, TruthFact

# Keys that indicate sensitive data — scrubbed before storage
SENSITIVE_KEYS = frozenset({
    "password", "passwd", "pwd",
    "secret", "secret_key",
    "token", "access_token", "refresh_token", "bearer_token",
    "api_key", "apikey",
    "auth_header", "authorization",
    "credential", "credentials",
    "private_key", "ssh_key",
    "connection_string",
})

# Patterns in values that suggest sensitive content
SENSITIVE_PATTERNS = re.compile(
    r"(bearer\s+\S+|sk-[a-zA-Z0-9]+|ghp_[a-zA-Z0-9]+|"
    r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----)",
    re.IGNORECASE,
)


def scrub_sensitive(data: Any) -> Any:
    """
    Recursively remove sensitive data from dicts/lists.

    Replaces values of sensitive keys with "[REDACTED]" and scrubs
    string values matching known secret patterns.

    Args:
        data: Input data (dict, list, or scalar)

    Returns:
        Scrubbed copy of the data (original is not mutated)
    """
    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            if k.lower() in SENSITIVE_KEYS:
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_sensitive(v)
        return scrubbed
    elif isinstance(data, list):
        return [scrub_sensitive(item) for item in data]
    elif isinstance(data, str):
        if SENSITIVE_PATTERNS.search(data):
            return "[REDACTED]"
        return data
    else:
        return data


def distill_output(
    raw_output: Any,
    source: str,
    confidence: float = 0.5,
    evidence: Optional[List[Evidence]] = None,
) -> Dict[str, TruthFact]:
    """
    Convert raw agent output into structured TruthFacts.

    Handles three input shapes:
    1. Dict with string keys → each key becomes a TruthFact
    2. AgentOutput-like dict with "payload" → distills the payload
    3. Any other value → wrapped as a single "result" fact

    Sensitive data is scrubbed before creating facts.

    Args:
        raw_output: The raw output from an agent or step
        source: Identifier for who produced this output (e.g. "step-analyst")
        confidence: Default confidence for distilled facts
        evidence: Optional evidence to attach to all facts

    Returns:
        Dict of fact_key → TruthFact
    """
    now = datetime.now(timezone.utc).isoformat()
    ev = evidence or []
    facts: Dict[str, TruthFact] = {}

    # Unwrap AgentOutput-like envelope
    if isinstance(raw_output, dict) and "payload" in raw_output:
        inner = raw_output["payload"]
        # Use summary as a fact if present
        if raw_output.get("summary"):
            facts["summary"] = TruthFact(
                value=raw_output["summary"],
                source=source,
                confidence=confidence,
                evidence=ev,
                updated_at=now,
            )
        # Distill the payload
        raw_output = inner if inner is not None else {}

    # Scrub before creating facts
    clean = scrub_sensitive(raw_output)

    if isinstance(clean, dict):
        for key, value in clean.items():
            # If value is already TruthFact-shaped, preserve it
            if isinstance(value, dict) and "value" in value:
                fact_confidence = value.get("confidence", confidence)
                fact_evidence = ev
                if value.get("evidence"):
                    fact_evidence = [
                        Evidence(**e) if isinstance(e, dict) else e
                        for e in value["evidence"]
                    ]
                facts[key] = TruthFact(
                    value=value["value"],
                    source=value.get("source", source),
                    confidence=fact_confidence,
                    evidence=fact_evidence,
                    updated_at=now,
                )
            else:
                facts[key] = TruthFact(
                    value=value,
                    source=source,
                    confidence=confidence,
                    evidence=ev,
                    updated_at=now,
                )
    elif clean is not None:
        facts["result"] = TruthFact(
            value=clean,
            source=source,
            confidence=confidence,
            evidence=ev,
            updated_at=now,
        )

    return facts


def merge_facts(
    existing: TruthContext,
    new_facts: Dict[str, TruthFact],
    source: str,
    max_history: int = 50,
) -> TruthContext:
    """
    Merge new facts into an existing TruthContext.

    For each new fact:
    - If key doesn't exist: add it
    - If key exists: update value, bump version, merge evidence

    Every merge is recorded in the history ledger (capped at max_history).

    Args:
        existing: The current TruthContext
        new_facts: Facts to merge in
        source: Who is performing the merge
        max_history: Maximum history entries to keep

    Returns:
        Updated TruthContext (existing is mutated and returned)
    """
    now = datetime.now(timezone.utc).isoformat()
    changed_keys = []

    for key, new_fact in new_facts.items():
        old_fact = existing.facts.get(key)
        if old_fact is not None:
            # Update existing fact — bump version, merge evidence
            old_fact.value = new_fact.value
            old_fact.confidence = new_fact.confidence
            old_fact.source = new_fact.source
            old_fact.version += 1
            old_fact.updated_at = now
            # Merge evidence (append new, deduplicate by pointer)
            seen_pointers = {e.pointer for e in old_fact.evidence}
            for ev in new_fact.evidence:
                if ev.pointer not in seen_pointers:
                    old_fact.evidence.append(ev)
                    seen_pointers.add(ev.pointer)
        else:
            # New fact — add directly
            existing.facts[key] = new_fact

        changed_keys.append(key)

    # Record in history
    if changed_keys:
        existing.history.append({
            "action": "merge",
            "source": source,
            "keys": changed_keys,
            "timestamp": now,
        })
        # Cap history
        if len(existing.history) > max_history:
            existing.history = existing.history[-max_history:]
        existing.version += 1

    return existing
