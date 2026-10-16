"""
Lost Reply, Safe Retry
======================
No LLM key. No Redis. No config. Just the mesh.

A request can time out after the peer has already done the work: the write
succeeded, the reply never arrived. The caller can't tell those two cases
apart, so it retries. If the peer treats the retry as new work, the write
happens twice.

This demo shows the failure and the fix:

  1. A billing peer charges a card, but its reply is lost.
  2. Without a key, the caller's retry charges the card a second time.
  3. With an idempotency key, the retry gets the first charge back. One charge.
  4. A retry that arrives while the first charge is still running waits for it,
     instead of starting a second one.

The pattern: the caller makes one key per piece of work and sends the same key
on every retry. The peer records the result under that key and answers repeats
from the record. Here the record is a dict, which is enough for one process. In
production keep it in Redis, so it survives restarts and every replica shares
it, and claim each key with SET NX so only one replica does the work.

Run:
    python examples/p2p_lost_reply_retry.py
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.core.agent import Agent

TIMEOUT = 1.0


def banner(n: int, text: str) -> None:
    print(f"\n{'━' * 68}\n  {n}. {text}\n{'━' * 68}")


def timed_out(reply) -> bool:
    """request() returns None if the send failed, or an error dict on timeout."""
    return reply is None or "error" in reply


class DemoAgent(Agent):
    """Deterministic stand-in so the demo needs no LLM key."""

    async def execute_task(self, task):
        return {"status": "completed", "by": self.role}


class BillingAgent(DemoAgent):
    role = "billing"
    capabilities = ["payments"]
    description = "Charges cards"

    def setup_ledger(self):
        self.ledger = []          # every charge that actually happened
        self.results = {}         # request_key -> future of the first result
        self.drop_next_reply = False
        self.charge_seconds = 0.0

    async def charge(self, amount: float) -> dict:
        await asyncio.sleep(self.charge_seconds)
        charge_id = f"ch_{len(self.ledger) + 1}"
        self.ledger.append((charge_id, amount))
        print(f"    billing: charged {amount:.2f} as {charge_id}")
        return {"charge_id": charge_id, "amount": amount}

    async def handle(self, msg):
        key = msg.data.get("request_key")
        if key is None:
            result = await self.charge(msg.data["amount"])
        else:
            # Claim the key before doing the work, so a retry that arrives
            # mid-charge waits for this charge instead of starting another.
            if key not in self.results:
                self.results[key] = asyncio.ensure_future(self.charge(msg.data["amount"]))
            else:
                print(f"    billing: seen {key[:8]} before, returning the first result")
            result = await self.results[key]

        if self.drop_next_reply:
            self.drop_next_reply = False
            print("    billing: (reply lost on the way back)")
            return
        await self.peers.respond(msg, result)

    async def run(self):
        while True:
            msg = await self.peers.receive(timeout=30)
            if msg is not None:
                asyncio.create_task(self.handle(msg))


class CheckoutAgent(DemoAgent):
    role = "checkout"
    capabilities = ["orders"]
    description = "Takes payment for an order"

    async def pay(self, payload: dict) -> dict:
        reply = await self.peers.request("billing", payload, timeout=TIMEOUT)
        if timed_out(reply):
            print("    checkout: no reply, retrying")
            reply = await self.peers.request("billing", payload, timeout=TIMEOUT)
        return reply


async def main():
    mesh = Mesh()
    billing = mesh.add(BillingAgent)
    checkout = mesh.add(CheckoutAgent)
    await mesh.start()
    billing.setup_ledger()
    billing_loop = asyncio.create_task(billing.run())

    try:
        banner(1, "Without a key: the reply is lost, the retry charges again")
        billing.drop_next_reply = True
        reply = await checkout.pay({"amount": 40.0})
        print("    checkout got:", reply)
        print(f">>> Charges for one order: {len(billing.ledger)}. The customer paid twice.")

        banner(2, "With a key: the reply is lost, the retry gets the first charge")
        billing.ledger.clear()
        billing.drop_next_reply = True
        key = str(uuid4())  # one key per order, reused on every retry
        reply = await checkout.pay({"request_key": key, "amount": 40.0})
        print("    checkout got:", reply)
        print(f">>> Charges for one order: {len(billing.ledger)}.")

        banner(3, "A retry that lands while the first charge is still running")
        billing.ledger.clear()
        billing.charge_seconds = TIMEOUT * 1.5  # slower than the caller's timeout
        key = str(uuid4())
        reply = await checkout.pay({"request_key": key, "amount": 40.0})
        print("    checkout got:", reply)
        print(f">>> Charges for one order: {len(billing.ledger)}. The retry waited for it.")
    finally:
        billing_loop.cancel()
        await mesh.stop()

    print()


if __name__ == "__main__":
    asyncio.run(main())
