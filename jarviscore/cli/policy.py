"""``jarviscore policy``: check a control policy file; review what strict mode refuses.

    jarviscore policy check [policy.yaml]   # every rule reads as written? (CONTROL_POLICY_PATH)
    jarviscore policy review [journal_dir]  # what strict mode would refuse, from a report-mode journal
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


def main() -> None:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    as_json = "--json" in sys.argv[1:]
    if not args or args[0] not in ("check", "review"):
        print(__doc__)
        sys.exit(1)
    sys.exit(_check(args[1:], as_json) if args[0] == "check" else _review(args[1:], as_json))
