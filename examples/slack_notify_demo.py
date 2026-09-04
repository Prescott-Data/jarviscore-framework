"""Offline test: kernel → coder → sandbox nexus_call → local vault → Slack."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent


class NotifierAgent(AutoAgent):
    role = "notifier"
    capabilities = ["notifications", "slack"]
    system_prompt = (
        "You are a notification agent. You send messages to Slack using "
        "nexus_call() against the Slack Web API (https://slack.com/api/chat.postMessage). "
        "Set `result` to the Slack API response dict."
    )


async def main():
    mesh = Mesh(config={"nexus_enabled": True})
    agent = mesh.add(NotifierAgent)
    try:
        await mesh.start()
        out = await agent.execute_task({
            "task": (
                "Send this exact message to the Slack channel #mesh-demo: "
                "'e2e test: agent -> nexus vault -> slack. reply ok if you see this.' "
                "Use nexus_call to POST https://slack.com/api/chat.postMessage "
                "with json={'channel': '#mesh-demo', 'text': ...}. "
                "Put the API response in `result`."
            ),
            "context": {"system": "slack"},
        })
        print("STATUS:", out.get("status"))
        print("OUTPUT:", str(out.get("output"))[:400])
    finally:
        await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
