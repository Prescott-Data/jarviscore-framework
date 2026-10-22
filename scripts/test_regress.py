"""Record a test-suite baseline and fail when a previously passing test stops passing.

Usage:
    python scripts/test_regress.py baseline [pytest args...]
    python scripts/test_regress.py compare  [pytest args...]
"""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASELINE = Path(".test-baseline.json")
JUNIT = Path(".test-results/junit.xml")


def run_suite(pytest_args: list[str]) -> dict[str, str]:
    JUNIT.parent.mkdir(exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", "tests", "-q",
           "--no-header", f"--junitxml={JUNIT}", *pytest_args]
    # Failures are expected here; the junit report decides the outcome.
    subprocess.run(cmd, check=False)
    results: dict[str, str] = {}
    for case in ET.parse(JUNIT).getroot().iter("testcase"):
        node = f"{case.get('classname')}::{case.get('name')}"
        if case.find("failure") is not None:
            results[node] = "failed"
        elif case.find("error") is not None:
            results[node] = "error"
        elif case.find("skipped") is not None:
            results[node] = "skipped"
        else:
            results[node] = "passed"
    return results


def summary(results: dict[str, str]) -> str:
    counts: dict[str, int] = {}
    for status in results.values():
        counts[status] = counts.get(status, 0) + 1
    return ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("baseline", "compare"):
        print(__doc__)
        return 2
    mode, pytest_args = sys.argv[1], sys.argv[2:]

    if mode == "compare" and not BASELINE.exists():
        print("No baseline found. Run `make baseline` first.")
        return 2

    results = run_suite(pytest_args)

    if mode == "baseline":
        BASELINE.write_text(json.dumps(results, indent=1, sort_keys=True))
        print(f"\nBaseline saved to {BASELINE}: {summary(results)}")
        return 0

    before: dict[str, str] = json.loads(BASELINE.read_text())
    regressed = sorted(t for t, s in before.items() if s ==
                       "passed" and results.get(t) in ("failed", "error"))
    missing = sorted(t for t, s in before.items() if s ==
                     "passed" and t not in results)
    fixed = sorted(t for t, s in before.items() if s in (
        "failed", "error") and results.get(t) == "passed")
    new_failing = sorted(t for t, s in results.items()
                         if t not in before and s in ("failed", "error"))

    print(f"\nBaseline: {summary(before)}")
    print(f"Now:      {summary(results)}")
    for title, items in (
        ("REGRESSED (passed in baseline, failing now)", regressed),
        ("MISSING (passed in baseline, not collected now)", missing),
        ("NEW TESTS FAILING", new_failing),
        ("FIXED since baseline", fixed),
    ):
        if items:
            print(f"\n{title}: {len(items)}")
            for t in items:
                print(f"  {t}")

    if regressed or missing or new_failing:
        print("\nRegression check FAILED")
        return 1
    print("\nRegression check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
