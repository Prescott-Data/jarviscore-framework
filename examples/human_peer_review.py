"""
A person and an agent on one mesh — no LLM key needed.

The launch desk drafts a post, finds whoever on the mesh can `review`, and asks
them. The draft appears in the person's terminal; they type their answer and
choose to send it as an approval or a rejection. If they reject it, the desk
revises with their reason and asks again.

    Terminal 1:  python examples/human_peer_review.py
    Terminal 2:  jarviscore human join alice --capabilities review --seed 127.0.0.1:7949

On two machines, run the desk with DESK_HOST set to its LAN or VPN address and
pass that address as --seed, with --host set to the joining machine's address.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import CustomAgent

HOST = os.getenv("DESK_HOST", "127.0.0.1")
PORT = int(os.getenv("DESK_PORT", "7949"))


class LaunchDesk(CustomAgent):
    role = "launch_desk"
    capabilities = ["drafting"]
    description = "Drafts launch posts and gets a person to sign them off."

    def draft(self, topic: str, notes: list) -> str:
        text = f"{topic}: agents and the people they work with, on one mesh."
        for note in notes:
            text += f" [revised: {note}]"
        return text

    async def on_peer_request(self, msg):
        return {"status": "success", "output": self.draft(msg.data.get("query", "JarvisCore"), [])}

    async def run(self):
        listener = asyncio.create_task(super().run())
        print("Waiting for someone with `review` to join the mesh...")
        while not self.shutdown_requested and not self.peers.discover(capability="review"):
            await asyncio.sleep(1)
        reviewer = self.peers.discover(capability="review")[0]
        print(f"{reviewer.role} joined. Asking for a review.")

        notes = []
        for attempt in range(1, 4):
            post = self.draft("JarvisCore 2.2", notes)
            print(f"\nDraft {attempt}: {post}")
            result = await self.peers.request_capability(
                "review", f"Review this launch post before it goes out:\n\n{post}", timeout=600
            )
            if result.get("status") == "success":
                answer = result["result"]["output"]
                print(f"✓ {answer['answered_by']} {answer['decision']}: {answer['response'] or '(no note)'}")
                break
            reason = result.get("error", "")
            print(f"✗ {reason}")
            notes.append(reason.split(": ", 1)[-1])
        print("\nDone. Ctrl-C to stop.")
        await listener


async def main():
    mesh = Mesh(config={"p2p_enabled": True, "bind_host": HOST, "bind_port": PORT,
                        "node_name": "launch-desk"})
    mesh.add(LaunchDesk)
    await mesh.start()
    print(f"Launch desk on the mesh at {HOST}:{PORT}")
    print(f"Join it:  jarviscore human join alice --capabilities review --seed {HOST}:{PORT}\n")
    await mesh.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
