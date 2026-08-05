"""
jarviscore inspect - read trace JSONL files and show what your agents did.

Every run already writes a flight record to traces/ (no Redis needed).
This command turns those files into something a human can read:

    jarviscore inspect                       # list recorded runs
    jarviscore inspect <workflow_id>         # timeline for one run
    jarviscore inspect <workflow_id> --errors    # failures and recoveries only
    jarviscore inspect <workflow_id> --step <step_id>   # one step
    jarviscore inspect --dir /path/to/traces     # non-default trace dir

Design rules:
- stdlib only, works offline, no framework imports required to read files
- never truncate silently: long values are clipped with an explicit marker
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

CLIP = 160


def _clip(value: Any, limit: int = CLIP) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]} [clipped: showing {limit} of {len(text)} chars]"


def _parse_ts(raw: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _load_events(path: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"type": "unparseable_line", "data": {"raw": _clip(line)}})
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
    return events


def _discover(trace_dir: str) -> Dict[str, List[str]]:
    """Map workflow_id -> trace file paths, newest runs last."""
    runs: Dict[str, List[str]] = defaultdict(list)
    if not os.path.isdir(trace_dir):
        return runs
    for name in sorted(os.listdir(trace_dir)):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(trace_dir, name)
        stem = name[: -len(".jsonl")]
        workflow_id = stem.rsplit("_", 1)[0] if "_" in stem else stem
        runs[workflow_id].append(path)
    return runs


def _run_summary(paths: List[str]) -> Dict[str, Any]:
    first_ts = last_ts = None
    steps = set()
    tokens = 0
    failures = 0
    status = "unknown"
    events_total = 0
    for path in paths:
        for event in _load_events(path):
            events_total += 1
            ts = _parse_ts(event.get("timestamp", ""))
            if ts is not None:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            step = event.get("step_id")
            if step:
                steps.add(step)
            etype = event.get("type", "")
            data = event.get("data", {}) or {}
            if etype == "llm_response":
                tokens += int(data.get("tokens", 0) or 0)
            elif etype in ("step_failed", "error_recovery"):
                failures += 1
            elif etype == "workflow_complete":
                status = str(data.get("status", "complete"))
    duration = ""
    if first_ts is not None and last_ts is not None:
        duration = f"{(last_ts - first_ts).total_seconds():.1f}s"
    return {
        "steps": len(steps),
        "events": events_total,
        "tokens": tokens,
        "failures": failures,
        "status": status,
        "started": first_ts.strftime("%Y-%m-%d %H:%M:%S") if first_ts else "?",
        "duration": duration,
    }


def _list_runs(trace_dir: str) -> int:
    runs = _discover(trace_dir)
    if not runs:
        print(f"no trace files in {trace_dir}/ (runs write them automatically)")
        return 1
    header = f"{'workflow':<32} {'started':<20} {'steps':>5} {'tokens':>8} {'fail':>4} {'dur':>8}  status"
    print(header)
    print("-" * len(header))
    ordered = sorted(runs.items(), key=lambda kv: _run_summary(kv[1])["started"])
    for workflow_id, paths in ordered:
        s = _run_summary(paths)
        print(
            f"{_clip(workflow_id, 32):<32} {s['started']:<20} {s['steps']:>5} "
            f"{s['tokens']:>8} {s['failures']:>4} {s['duration']:>8}  {s['status']}"
        )
    print(f"\n{len(runs)} run(s). Inspect one: jarviscore inspect <workflow>")
    return 0


_RENDERERS = {
    "workflow_start": lambda d: f"workflow started ({d.get('step_count', '?')} steps planned)",
    "workflow_complete": lambda d: f"workflow {d.get('status', 'complete')}: {_clip(d.get('summary', ''))}",
    "step_claimed": lambda d: f"claimed by {d.get('agent_id', '?')}",
    "step_complete": lambda d: f"step complete: {_clip(d.get('summary', d))}",
    "step_failed": lambda d: f"STEP FAILED: {_clip(d.get('error', d))}",
    "thinking": lambda d: f"thinking: {_clip(d.get('thought', d))}",
    "kernel_delegate": lambda d: f"delegated to {d.get('subagent', '?')}: {_clip(d.get('task', ''))}",
    "subagent_yield": lambda d: f"subagent {d.get('subagent', '?')} yielded: {_clip(d.get('reason', ''))}",
    "tool_start": lambda d: f"tool {d.get('tool_name', d.get('tool', '?'))} {_clip(d.get('params', ''))}",
    "tool_result": lambda d: f"  -> {_clip(d.get('result', d))}",
    "llm_request": lambda d: f"llm call ({d.get('provider', '?')}/{d.get('model', '?')})",
    "llm_response": lambda d: (
        f"  -> {d.get('tokens', '?')} tokens in {d.get('latency_ms', '?')}ms"
    ),
    "error_recovery": lambda d: f"RECOVERY: {_clip(d.get('error', ''))} -> {_clip(d.get('action', ''))}",
    "hitl_task_created": lambda d: f"HITL task created: {_clip(d)}",
    "hitl_waiting": lambda d: f"HITL waiting: {_clip(d.get('reason', ''))}",
    "hitl_resolved": lambda d: f"HITL resolved: {d.get('outcome', '?')}",
    "mailbox_send": lambda d: f"mail -> {d.get('target', '?')}: {_clip(d.get('message_preview', ''))}",
    "mailbox_receive": lambda d: f"mail <- {d.get('count', '?')} message(s)",
    "context_snapshot": lambda d: f"context snapshot ({d.get('fact_count', '?')} facts, v{d.get('version', '?')})",
}

_ERROR_TYPES = {"step_failed", "error_recovery", "unparseable_line"}


def _render_event(event: Dict[str, Any]) -> Tuple[str, str, bool]:
    etype = event.get("type", "?")
    data = event.get("data", {}) or {}
    renderer = _RENDERERS.get(etype)
    text = renderer(data) if renderer else f"{etype}: {_clip(data)}"
    ts = event.get("timestamp", "")
    clock = ts[11:19] if len(ts) >= 19 else "?"
    return clock, text, etype in _ERROR_TYPES


def _show_run(trace_dir: str, workflow_id: str, *, step: Optional[str], errors_only: bool) -> int:
    runs = _discover(trace_dir)
    matches = [wid for wid in runs if wid == workflow_id] or [
        wid for wid in runs if wid.startswith(workflow_id)
    ]
    if not matches:
        print(f"no run matching '{workflow_id}' in {trace_dir}/", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"'{workflow_id}' is ambiguous: {', '.join(sorted(matches)[:6])}", file=sys.stderr)
        return 1
    wid = matches[0]
    events: List[Dict[str, Any]] = []
    for path in runs[wid]:
        events.extend(_load_events(path))
    events.sort(key=lambda e: e.get("timestamp", ""))

    s = _run_summary(runs[wid])
    print(f"run {wid} | started {s['started']} | {s['steps']} step(s) | "
          f"{s['tokens']} tokens | {s['failures']} failure(s) | {s['duration']} | {s['status']}")
    current_step = object()
    shown = 0
    for event in events:
        if step and event.get("step_id") != step:
            continue
        clock, text, is_error = _render_event(event)
        if errors_only and not is_error:
            continue
        event_step = event.get("step_id")
        if event_step != current_step:
            current_step = event_step
            print(f"\n[{event_step or 'workflow'}]")
        marker = "!! " if is_error else "   "
        print(f"{marker}{clock}  {text}")
        shown += 1
    if shown == 0:
        print("no events matched the filters")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jarviscore inspect",
        description="Read recorded traces and show what your agents actually did.",
    )
    parser.add_argument("workflow", nargs="?", help="workflow id (prefix ok); omit to list runs")
    parser.add_argument("--dir", default="traces", help="trace directory (default: ./traces)")
    parser.add_argument("--step", default=None, help="only events for this step id")
    parser.add_argument("--errors", action="store_true", help="failures and recoveries only")
    args = parser.parse_args()

    if args.workflow is None:
        sys.exit(_list_runs(args.dir))
    sys.exit(_show_run(args.dir, args.workflow, step=args.step, errors_only=args.errors))


if __name__ == "__main__":
    main()
