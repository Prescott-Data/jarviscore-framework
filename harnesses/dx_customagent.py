#!/usr/bin/env python3
"""DX Harness 1 - the CustomAgent developer journey.

Simulates a developer following the CustomAgent guide end to end:
message-driven agent, workflow execution, result identity, fanout.
No LLM required - this is the infrastructure contract.
"""
import asyncio
import sys

PASS, FAIL = "✅", "❌"
failures = []


def check(name, cond, detail=""):
    print(f"  {PASS if cond else FAIL} {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


async def main():
    from jarviscore import Mesh, MeshMode, CustomAgent

    class AnalystAgent(CustomAgent):
        role = "analyst"
        capabilities = ["analysis"]

        async def on_peer_request(self, msg):
            payload = msg.data.get("payload") or msg.data.get("task", "")
            return {"status": "success", "read": str(payload).upper()}

    print("== CustomAgent developer journey ==")

    mesh = Mesh(mode=MeshMode.AUTONOMOUS)
    mesh.add(AnalystAgent)
    await mesh.start()
    try:
        # 1. Workflow execution through on_peer_request delegation
        results = await mesh.workflow("dx-custom-1", [
            {"id": "read_a", "agent": "analyst", "task": "hello"},
            {"id": "read_b", "agent": "analyst", "task": "world"},
        ])
        check("workflow returns results in step order", len(results) == 2)
        check("every result carries step_id (#62)",
              [r.get("step_id") for r in results] == ["read_a", "read_b"],
              f"got {[r.get('step_id') for r in results]}")
        check("success results carry the agent's payload",
              results[0].get("output", {}).get("read") == "HELLO",
              f"got {results[0]}")

        # 2. Dynamic fan-out (#52)
        fanout = await mesh.fanout(
            "dx-custom-fanout",
            agent="analysis",           # capability-based resolution
            items=["alpha", "beta", "gamma", "delta"],
            task=lambda s: f"read {s}",
            context=lambda s: {"payload": s},
            concurrency=2,
            budget=3,
        )
        check("fanout respects the budget honestly",
              len(fanout.results) == 3 and fanout.skipped == ["delta"])
        check("fanout results in item order with identity",
              [r["item"] for r in fanout.results] == ["alpha", "beta", "gamma"]
              and all("step_id" in r for r in fanout.results))
        check("fanout aggregation works",
              fanout.aggregate(len) == 3)
    finally:
        await mesh.stop()

    print()
    if failures:
        print(f"{FAIL} CustomAgent journey: {len(failures)} failure(s): {failures}")
        sys.exit(1)
    print(f"{PASS} CustomAgent journey: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
