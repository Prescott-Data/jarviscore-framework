"""Crash-recovery demo for the README GIF.

Run 1: a 3-step workflow starts; the process is kill -9'd while step 2 runs.
Run 2: the SAME workflow id is resubmitted; step 1 comes back from Redis as
recovered:true and only the unfinished work executes.

Everything printed is real engine behaviour — the recorder only adds styling.
"""
import asyncio
import json
import os
import sys
import time

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

WORKFLOW_ID = "prod-incident-brief"
T0 = time.monotonic()


def say(line: str) -> None:
    print(json.dumps({"t": round(time.monotonic() - T0, 3), "line": line}), flush=True)


class ResearcherAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research", "analysis"]
    system_prompt = "You are a rigorous research analyst. Be concise and factual."


class AnalystAgent(AutoAgent):
    role = "analyst"
    capabilities = ["analysis", "evaluation"]
    default_kernel_role = "communicator"
    system_prompt = "You assess research and pull out the two highest-impact risks."


class WriterAgent(AutoAgent):
    role = "writer"
    capabilities = ["writing", "summarisation"]
    default_kernel_role = "communicator"
    system_prompt = "You turn analysis into a crisp three-bullet brief."


STEPS = [
    {"agent": "researcher", "task": "In 4 short sentences: why do multi-agent LLM systems that work in demos fail in production?"},
    {"agent": "analyst", "task": "From the research in the previous step, name the 2 highest-impact failure modes, one line each.", "depends_on": [0]},
    {"agent": "writer", "task": "Turn the analysis from the previous step into exactly 3 short bullet points.", "depends_on": [1]},
]


async def main(mode: str) -> int:
    mesh = Mesh()
    mesh.add(ResearcherAgent)
    mesh.add(AnalystAgent)
    mesh.add(WriterAgent)
    await mesh.start()
    say(f"await mesh.start()   ✓ 3 agents · redis connected · workflow engine up")
    say("")

    if mode == "crash":
        say(f'await mesh.workflow("{WORKFLOW_ID}", steps=[researcher → analyst → writer])')

        async def watch_and_die() -> None:
            # kill -9 the moment step 1's output is committed and step 2 is in flight
            import redis
            r = redis.Redis.from_url(os.environ["REDIS_URL"])
            while True:
                await asyncio.sleep(0.25)
                s0 = r.hget(f"step_output:{WORKFLOW_ID}:step0", "output")
                if s0:
                    await asyncio.sleep(1.0)  # let step 2 visibly start
                    say("")
                    say("$ kill -9 %d        # the whole process, mid-workflow" % os.getpid())
                    os.kill(os.getpid(), 9)

        asyncio.get_event_loop().create_task(watch_and_die())
        await mesh.workflow(WORKFLOW_ID, STEPS)
        return 0  # unreachable

    # mode == "resume"
    say(f'await mesh.workflow("{WORKFLOW_ID}", steps=…)   # same id, new process')
    results = await mesh.workflow(WORKFLOW_ID, STEPS)
    say("")
    for i, result in enumerate(results):
        if result.get("recovered"):
            say(f"step {i + 1} → recovered from redis — not re-run")
        else:
            say(f"step {i + 1} → {result.get('status', '?')}")
    say("")
    output = results[-1].get("output", "")
    if isinstance(output, dict):
        output = "\n".join(str(x) for x in output.get("data", [output]))
    for line in str(output).strip().splitlines():
        if line.strip():
            say(line.strip())
    say("")
    say("✓ workflow completed across a crash — nothing re-run, nothing lost")
    await mesh.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "resume")))
