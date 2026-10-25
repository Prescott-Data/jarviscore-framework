"""``jarviscore replay``: re-simulate recorded agent runs from the journal, every effect stubbed.

    jarviscore replay                      # every replayable run in JOURNAL_DIR
    jarviscore replay <journal_dir> [run]  # one run, e.g. wf-12/s1
    ... --json

Each run's agent is rebuilt and answered from its record: every model call,
gate and tool result. Nothing is called and nothing acts. A run reproduces when
the agent makes the same decisions (each tool, with the same arguments) and ends
the same way. Exit status: 0 all reproduced, 1 any diverged, 2 nothing to replay.
"""
import asyncio
import json
import os
import sys


def main() -> None:
    from jarviscore.evidence.journal import journal_root
    from jarviscore.evidence.replay import replay, runs

    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    as_json = "--json" in sys.argv[1:]
    root = args[0] if args else journal_root()
    if not root or not os.path.isdir(root):
        print(f"No journal at {root or '(journal switched off)'}.")
        sys.exit(2)
    targets = args[1:] or runs(root)
    if not targets:
        print(f"{root}: no recorded agent runs (JOURNAL_CAPTURE=full records them).")
        sys.exit(2)

    async def all_reports():
        reports = []
        for run in targets:
            try:
                reports.append(await replay(root, run))
            except Exception as exc:  # noqa: BLE001 - one unreplayable run is reported, not fatal
                from jarviscore.evidence.replay import ReplayReport

                reports.append(ReplayReport(run=run, divergence=f"{type(exc).__name__}: {exc}"))
        return reports

    reports = asyncio.run(all_reports())
    if as_json:
        print(json.dumps([report.__dict__ for report in reports], indent=2))
    else:
        for report in reports:
            print(report.summary())
            for note in report.notes:
                print(f"  - {note}")
        reproduced = sum(r.reproduced for r in reports)
        print(f"\n{reproduced} of {len(reports)} run(s) reproduced.")
    sys.exit(0 if all(r.reproduced for r in reports) else 1)
