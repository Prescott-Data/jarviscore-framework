"""``jarviscore evidence``: what agents did for a person, or for a whole tenant.

    jarviscore evidence acme/u_1                   # each run done for that person
    jarviscore evidence acme/                      # ... for anyone in tenant acme
    jarviscore evidence acme/ path/to/journal      # another journal than JOURNAL_DIR
    jarviscore evidence acme/ --export DIR         # copy those runs for an auditor
    jarviscore evidence acme/ --export DIR --content   # ... with what replay needs (personal data)
    jarviscore evidence acme/u_1 --json
    jarviscore evidence acme/u_1 --erase           # what erasing their replay content would remove
    jarviscore evidence acme/u_1 --erase --yes     # erase it; the journal still verifies

An export is checked on its own with ``jarviscore verify --export DIR``. Exit
status is 0, or 2 when there is no journal or nothing was done for them.
"""
import json
import os
import sys


def _option(name: str):
    argv = sys.argv[1:]
    if name in argv:
        at = argv.index(name)
        if at + 1 < len(argv) and not argv[at + 1].startswith("--"):
            return argv[at + 1]
        print(f"{name} needs a value")
        sys.exit(2)
    return None


def main() -> None:
    from jarviscore.evidence.journal import journal_root
    from jarviscore.evidence.people import account, erase, export

    destination = _option("--export")
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != destination]
    if not args:
        print(__doc__)
        sys.exit(1)
    who = args[0]
    root = args[1] if len(args) > 1 else journal_root()
    if not root or not os.path.isdir(root):
        print(f"No journal at {root or '(journal switched off)'}.")
        sys.exit(2)
    if "--erase" in sys.argv[1:]:
        done = "--yes" in sys.argv[1:]
        counts = erase(root, who, dry_run=not done)
        if "--json" in sys.argv[1:]:
            print(json.dumps({"for": who, "erased": done, **counts}, indent=2))
        else:
            verb = "Erased" if done else "Would erase"
            print(f"{verb} {counts['erased']} replay content file(s) from {counts['runs']} run(s) for {who}; "
                  f"kept {counts['kept_shared']} also used by others' runs.")
            print("The journal still verifies; those runs can no longer be replayed."
                  if done else "Run again with --yes to erase.")
        sys.exit(0)
    if destination:
        manifest = export(root, who, destination, content="--content" in sys.argv[1:])
        if "--json" in sys.argv[1:]:
            print(json.dumps(manifest, indent=2))
        else:
            print(f"Exported {len(manifest['runs'])} run(s) for {who} to {destination}.")
            if manifest["left_out_shared"]:
                print(f"Left out {len(manifest['left_out_shared'])} run(s) that also acted for others: "
                      + ", ".join(manifest["left_out_shared"]))
            if manifest["content"] is not None:
                print(f"With {manifest['content']} content file(s) for replay.")
            print(f"Check it: jarviscore verify --export {destination}")
        sys.exit(0 if manifest["runs"] else 2)
    runs = account(root, who)
    if "--json" in sys.argv[1:]:
        print(json.dumps({"root": root, "for": who, "runs": runs}, indent=2))
        sys.exit(0 if runs else 2)
    if not runs:
        print(f"{root}: nothing recorded as done for {who}.")
        sys.exit(2)
    for run in runs:
        flags = " (also acted for others)" if run["shared"] else ""
        print(f"{run['started']}  {run['run']}  agent={run['agent']}  for={', '.join(run['for'])}"
              f"  outcome={run['outcome'] or '-'}{flags}")
        for d in run["decisions"]:
            state = "refused" if d["outcome"] == "deny" and d["enforced"] else (
                "would refuse" if d["outcome"] == "deny" else "allowed")
            print(f"    {d['at']}  {state:<12} {d['sink']:<9} {d['action'] or '':<8} {d['target']}"
                  + (f"  [{d['rule']}]" if d["rule"] else "")
                  + (f"  scopes: {', '.join(d['scopes'])}" if d.get("scopes") else ""))
            if d.get("reason") and d["outcome"] == "deny":
                print(f"        {d['reason']}")
        for a in run["approvals"]:
            print(f"    {a['at']}  {a['kind']:<20} {a['decision'] or ''} {a['by'] or ''}")
    print(f"\n{len(runs)} run(s), {sum(len(r['decisions']) for r in runs)} decision(s), "
          f"{sum(r['effects'] for r in runs)} effect(s), {sum(r['refused'] for r in runs)} refused.")
    sys.exit(0)
