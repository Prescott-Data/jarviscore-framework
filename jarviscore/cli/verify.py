"""``jarviscore verify``: check the journal of decisions and provider calls.

    jarviscore verify                 # the deployment's journal (JOURNAL_DIR)
    jarviscore verify path/to/journal # another copy, e.g. one handed to an auditor
    jarviscore verify --json          # the report as JSON

Exit status is 0 when every record is intact, 1 when any is not, 2 when there is
no journal to check. Nothing here needs the deployment, its keys or the network.
"""
import json
import os
import sys


def main() -> None:
    from jarviscore.evidence.journal import journal_root, verify

    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    as_json = "--json" in sys.argv[1:]
    root = args[0] if args else journal_root()
    if not root or not os.path.isdir(root):
        print(f"No journal at {root or '(journal switched off)'}.")
        sys.exit(2)
    report = verify(root)
    if as_json:
        print(json.dumps({
            "root": report.root, "ok": report.ok, "runs": report.runs, "events": report.events,
            "effects": report.effects, "provider_calls": report.effects, "refused": report.refused,
            "refused_in_preview": report.refused_in_preview, "problems": report.problems,
        }, indent=2))
    else:
        print(f"{root}: {report.summary()}")
        for problem in report.problems:
            print(f"  - {problem}")
        print(
            "\nChecked: each run's hash chain, its head in the head log, that every "
            "effect (provider calls, code, processes, artifacts, workspace, memory, peers, "
            "outputs) followed an allow decision, and that every grounded call cites reads "
            "in the record.\nNot covered: a rewrite of the whole "
            "journal by whoever controls it, until checkpoints are anchored outside it."
        )
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
