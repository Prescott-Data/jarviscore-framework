"""An agent that remembers across runs. Run it twice:

    python agent_that_remembers.py "Remember: Acme renews 3 March 2027, contact Jane Mwangi."
    python agent_that_remembers.py "When does Acme renew, and who should I call?"
"""
import asyncio
import sys

from jarviscore import AutoAgent, Mesh


class AccountManager(AutoAgent):
    role = "account_manager"
    capabilities = ["client_accounts"]
    system_prompt = "You keep important client facts and use them when asked."


async def main(message: str):
    mesh = Mesh()
    mesh.add(AccountManager)
    await mesh.start()
    try:
        result = await mesh.run_task(agent="account_manager", task=message)
        print(result["result_summary"])
    finally:
        await mesh.stop()


asyncio.run(main(" ".join(sys.argv[1:])))
