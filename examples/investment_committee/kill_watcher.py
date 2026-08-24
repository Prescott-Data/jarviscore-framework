"""Kills the committee process once the four parallel analyst steps have committed
and a downstream step (risk/memo/decision) is in flight — the worst possible moment."""
import os
import subprocess
import sys
import time

import redis

WF_ID = sys.argv[1] if len(sys.argv) > 1 else "committee-NVDA-demo"
r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6390/0"))

ANALYSTS = ["market_analysis", "financial_analysis", "technical_analysis", "knowledge_retrieval"]

proc = subprocess.Popen(
    [sys.executable, "committee.py", "--mode", "full", "--ticker", "NVDA",
     "--amount", "1500000", "--workflow-id", WF_ID],
    cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
)

killed = False
deadline = time.time() + 600
while time.time() < deadline:
    time.sleep(1)
    if proc.poll() is not None:
        print(f"[watcher] committee exited on its own: {proc.returncode}", flush=True)
        sys.exit(1)
    done = sum(1 for s in ANALYSTS if r.hget(f"step_output:{WF_ID}:{s}", "output"))
    print(f"[watcher] analysts committed: {done}/4", flush=True)
    if done >= 4:
        time.sleep(3)  # let risk_assessment start
        print(f"[watcher] kill -9 {proc.pid} — 4 analysts paid, memo not written", flush=True)
        proc.kill()
        killed = True
        break

sys.exit(0 if killed else 2)
