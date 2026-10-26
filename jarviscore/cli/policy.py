"""``jarviscore policy``: check a control policy file; review what strict mode refuses.

    jarviscore policy check [policy.yaml]   # every rule reads as written? (CONTROL_POLICY_PATH)
    jarviscore policy review [journal_dir]  # what strict mode would refuse, from a report-mode journal
    jarviscore policy scopes [policy.yaml]  # who may do what: each operation's scope, and the grants on file
    ... --json                              # either, as JSON

``check`` exits 1 when a rule cannot be read (a deployment would refuse what it
matches, or everything). ``review`` exits 0; it reads, and changes nothing.
"""
import json
import os
import sys


def _check(args, as_json: bool) -> int:
    from jarviscore.control.policy import check_policy
    from jarviscore.execution.isolation import confinement_unavailable_reason
    from jarviscore.config.settings import settings

    path = args[0] if args else os.environ.get("JARVISCORE_CONTROL_POLICY") or getattr(settings, "control_policy_path", "")
    if not path:
        print("No policy file: pass one, or set CONTROL_POLICY_PATH.")
        return 2
    problems, summary = check_policy(str(path))
    mode = os.environ.get("JARVISCORE_CONTROL_MODE") or getattr(settings, "control_mode", "report")
    confinement = confinement_unavailable_reason()
    if as_json:
        print(json.dumps({"path": str(path), "ok": not problems, "problems": problems, "sections": summary,
                          "mode": mode, "confinement": confinement or "available"}, indent=2))
        return 1 if problems else 0
    print(f"{path}: " + (", ".join(f"{n} {k}" for k, n in summary.items()) if summary else "unreadable"))
    for problem in problems:
        print(f"  - {problem}")
    print(f"\nMode: {mode}. Sandbox confinement: {'available' if confinement is None else confinement}.")
    if str(mode).lower() == "strict" and confinement is not None:
        print("Strict mode refuses model-written code here unless an effects rule allows {sink: code}.")
    print("Every rule reads as written." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


def _review(args, as_json: bool) -> int:
    from jarviscore.control.policy import review_journal
    from jarviscore.evidence.journal import journal_root

    root = args[0] if args else journal_root()
    if not root or not os.path.isdir(root):
        print(f"No journal at {root or '(journal switched off)'}.")
        return 2
    groups = review_journal(root)
    if as_json:
        print(json.dumps({"root": root, "refusals": groups}, indent=2))
        return 0
    if not groups:
        print(f"{root}: nothing refused, and nothing strict mode would refuse.")
        return 0
    for group in groups:
        print(f"{group['count']:>5} x {group['state']:<24} {group['rule']:<26} {group['sink']} "
              f"{group['action'] or ''} {group['target']}")
        if group["remedy"]:
            print(f"        {group['remedy']}")
    return 0


def _scopes(args, as_json: bool) -> int:
    from jarviscore.config.settings import settings
    from jarviscore.control.scopes import parse_section

    path = args[0] if args else os.environ.get("JARVISCORE_CONTROL_POLICY") or getattr(settings, "control_policy_path", "")
    if not path:
        print("No policy file: pass one, or set CONTROL_POLICY_PATH.")
        return 2
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        data = json.loads(text) if str(path).endswith(".json") else __import__("yaml").safe_load(text)
    except Exception as exc:  # noqa: BLE001
        print(f"{path} cannot be read ({exc}).")
        return 1
    section = parse_section((data or {}).get("scopes") if isinstance(data, dict) else None)
    require = [{
        "name": r.name, "match": dict(r.match), "requires": r.requires, "approved_by": r.approved_by,
        "limits": [{"field": l.field, "kind": l.kind, "relation": l.relation, "term": l.term} for l in r.limits],
        **({"invalid": r.invalid} if r.invalid else {}),
    } for r in section.require]
    if as_json:
        print(json.dumps({"path": str(path), "require": require, "grants": section.grants,
                          "unattended": section.unattended, "problems": list(section.problems)}, indent=2))
        return 1 if section.problems or any(r.invalid for r in section.require) else 0
    if not require:
        print(f"{path}: no scope requirements; no operation needs a scope.")
    for r in require:
        match = ", ".join(f"{k}={v}" for k, v in r["match"].items())
        who = []
        if r["requires"]:
            who.append(f"the person needs {r['requires']}")
        if r["approved_by"]:
            who.append(f"an approver needs {r['approved_by']}")
        print(f"{r['name']}: {match}\n    {'; '.join(who) or '(unreadable)'}")
        for l in r["limits"]:
            print(f"    within: {l['field']} ({l['kind']}) {l['relation'].replace('_', ' ')} the grant's {l['term']!r}")
        if r.get("invalid"):
            print(f"    UNREADABLE ({r['invalid']}): refuses what it matches")
        elif "atom" in r["match"] and not ({"path", "method", "sink"} & set(r["match"])):
            print("    note: matched by integration name, so only calls from that integration are held to it; "
                  "match method and path to hold any code that reaches the same operation")
    if section.grants:
        print("\nGrants on file (your application's grants come first for any scope it names):")
        for person, grant in sorted(section.grants.items()):
            print(f"  {person}: " + ", ".join(
                name + (f" {terms}" if terms else "") for name, terms in sorted(grant.items())))
    print(f"\nWork done for no one holds: {', '.join(sorted(section.unattended)) or 'nothing'}.")
    for problem in section.problems:
        print(f"  - {problem}")
    return 1 if section.problems or any(r.get("invalid") for r in require) else 0


def main() -> None:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    as_json = "--json" in sys.argv[1:]
    if not args or args[0] not in ("check", "review", "scopes"):
        print(__doc__)
        sys.exit(1)
    command = {"check": _check, "review": _review, "scopes": _scopes}[args[0]]
    sys.exit(command(args[1:], as_json))
