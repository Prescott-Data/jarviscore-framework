"""Native TypeSafe Jev decisions inside a JarvisCore agent.

Requirements:
  pip install "jarviscore-framework[typesafe]"
  export TYPESAFE_API_KEY=...

Run:
  python examples/typesafe_jev_decisions.py

Expected shape:
    model:      jev-1.13.0
    owner:      engineering (confidence 1.00)
    severity:   2.00 / 2
    urgent:     0.97

Exact scores vary with model updates; each value remains within its declared type.
"""

import asyncio

from dotenv import load_dotenv

load_dotenv()

from jarviscore import CustomAgent, Mesh  # noqa: E402


class IncidentTriageAgent(CustomAgent):
    role = "incident_triage"
    capabilities = ["incident_classification"]

    async def execute_task(self, task):
        ticket = task.get("params", {}).get("ticket", "")
        if self.decisions is None:
            return {
                "status": "failure",
                "error": "Set TYPESAFE_API_KEY and install jarviscore-framework[typesafe].",
            }

        result = await self.decisions.evaluate(
            state={"ticket": ticket},
            questions={
                "owner": {
                    "type": "choice",
                    "instructions": "Which team should own this incident?",
                    "criteria": {
                        "billing": "Charges, invoices, refunds, and subscriptions.",
                        "engineering": "Deploy failures, outages, and server errors.",
                        "support": "Product usage and account assistance.",
                    },
                },
                "severity": {
                    "type": "score",
                    "instructions": "How severe is the customer impact?",
                    "criteria": [
                        "Cosmetic or no customer impact.",
                        "Degraded for some customers.",
                        "A critical customer journey is unavailable.",
                    ],
                },
                "urgent": {
                    "type": "noul",
                    "instructions": "Does this incident require immediate attention?",
                },
            },
        )

        return {
            "status": "success",
            "output": result.to_dict(),
        }


async def main() -> None:
    mesh = Mesh(config={"p2p_enabled": False})
    mesh.add(IncidentTriageAgent)
    await mesh.start()
    try:
        results = await mesh.workflow(
            "jev-incident-triage",
            [
                {
                    "agent": "incident_triage",
                    "task": "Classify this incident with typed decisions.",
                    "params": {
                        "ticket": (
                            "Our checkout deploy failed twice and customers are "
                            "seeing 500 errors. Revenue is affected right now."
                        )
                    },
                }
            ],
        )
    finally:
        await mesh.stop()

    decision = results[0]["output"]
    owner = decision["answers"]["owner"]
    severity = decision["answers"]["severity"]
    urgent = decision["answers"]["urgent"]

    print(f"model:      {decision['model']}")
    print(f"owner:      {owner['choice']} (confidence {owner['confidence']:.2f})")
    print(f"severity:   {severity['score']:.2f} / 2")
    print(f"urgent:     {urgent['noul']:.2f}")
    print(f"tokens:     {decision['usage']}")
    print(f"request id: {decision['request_id']}")


if __name__ == "__main__":
    asyncio.run(main())