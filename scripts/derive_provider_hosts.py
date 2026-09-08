"""Extract the API hosts each provider's atoms actually call.

Run from the repo root. Prints a summary and writes the derived data as a Python
literal so it can be reviewed before being committed into providers.py.
"""

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ATOMS = Path("jarviscore/integrations/atoms")


def literal_parts(node):
    """Reconstruct a string from a Constant or JoinedStr, placeholders as '{}'."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            else:
                out.append("{}")
        return "".join(out)
    return None


def hosts_in(source):
    found = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        text = literal_parts(node)
        if not text or "://" not in text:
            continue
        for match in re.finditer(r"https?://([^/\s'\"]+)", text):
            host = match.group(1).lower().strip()
            if host:
                found.add(host)
    return found


def main():
    by_provider = defaultdict(set)
    for provider_dir in sorted(p for p in ATOMS.iterdir() if p.is_dir()):
        for atom in provider_dir.glob("*.py"):
            by_provider[provider_dir.name] |= hosts_in(atom.read_text())

    # A bare "{}" is the whole host coming from user data. It constrains nothing,
    # so it is not written: those providers are bound by the domain recorded on
    # their connection instead.
    cleaned = {
        provider: sorted(h for h in hosts if h != "{}")
        for provider, hosts in by_provider.items()
    }
    cleaned = {p: h for p, h in cleaned.items() if h}

    dynamic = sorted(set(by_provider) - set(cleaned))
    templated = {
        p: [h for h in hs if "{}" in h] for p, hs in cleaned.items()
    }
    templated = {p: h for p, h in templated.items() if h}

    print(f"providers with literal hosts: {len(cleaned)}")
    print(f"providers with tenant-subdomain patterns: {len(templated)}")
    for provider, hosts in sorted(templated.items()):
        print(f"  {provider}: {hosts}")
    print()
    print(f"bound by connection domain only ({len(dynamic)}): {dynamic}")

    out = Path("jarviscore/nexus/_data/provider_hosts.json")
    out.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {out} ({sum(len(v) for v in cleaned.values())} hosts)")


if __name__ == "__main__":
    sys.exit(main())
