"""
ReasoningAgent — one disciplined structured completion per task.

The third point on the control spectrum:

    CustomAgent      — you write everything (infrastructure only)
    ReasoningAgent   — you write the prompt; ONE llm.generate() per task
    AutoAgent        — you write nothing (full kernel autonomy)

This is arguably the most common LLM-agent shape — render a system prompt,
make one structured completion, parse JSON, return the standard envelope —
and previously it fit neither profile: AutoAgent routed analysis prompts
into codegen (TOOL/DONE protocol violations), CustomAgent made every
project re-implement the LLM wiring (issue #63, JC-001).

Example:
    class MarketAnalyst(ReasoningAgent):
        role = "market_analyst"
        capabilities = ["analysis"]
        system_prompt = "You are a rigorous market analyst. Return JSON..."

    # execute_task({"task": "Analyse EURUSD H1"}) → one completion →
    # {"status": "success", "payload": {...parsed JSON...}, ...}
"""
import json
import logging
import re
from typing import Any, Dict, Optional

from jarviscore.core.profile import Profile

logger = logging.getLogger(__name__)

_JSON_ONLY_INSTRUCTION = (
    "\n\nRespond with a single valid JSON object and nothing else."
)


def _parse_json_object(content: str) -> Optional[Dict[str, Any]]:
    """Parse a JSON object from a completion, tolerating code fences."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                obj = json.loads(text[start:end + 1])
                return obj if isinstance(obj, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
    return None


class ReasoningAgent(Profile):
    """One structured completion against the system prompt per task.

    Class attributes (beyond role/capabilities):
        system_prompt:      Required — the agent's expertise.
        expects_json:       Parse the completion as a JSON object (default True).
                            Parse failure returns a clean failure envelope, never
                            a silent raw string masquerading as structure.
        temperature:        Sampling temperature (default 0.0 — analysis wants
                            determinism; override for creative agents).
        max_output_tokens:  Completion cap (default 4000).
        model:              Optional model/deployment override.
    """

    system_prompt: Optional[str] = None
    expects_json: bool = True
    temperature: float = 0.0
    max_output_tokens: int = 4000
    model: Optional[str] = None

    def __init__(self, agent_id: Optional[str] = None):
        super().__init__(agent_id)
        if not self.system_prompt:
            raise ValueError(
                f"{self.__class__.__name__} must define 'system_prompt' class attribute\n"
                f"Example: system_prompt = 'You are an expert...'"
            )
        self.llm: Any = None

    async def setup(self) -> None:
        await super().setup()
        from jarviscore.execution import create_llm_client

        config = self._mesh.config if self._mesh else {}
        self.llm = create_llm_client(config)
        self._logger.info(f"ReasoningAgent ready: {self.agent_id}")

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Run one structured completion and return the standard envelope."""
        if self.llm is None:
            raise RuntimeError(
                f"Agent '{self.agent_id}' used before mesh.start() — "
                f"setup() wires the LLM client. Call `await mesh.start()` first."
            )

        prompt = task.get("task", "") if isinstance(task, dict) else str(task)
        user_content = prompt + (_JSON_ONLY_INSTRUCTION if self.expects_json else "")
        messages = [
            {"role": "system", "content": self.system_prompt or ""},
            {"role": "user", "content": user_content},
        ]

        kwargs: Dict[str, Any] = {"max_tokens": self.max_output_tokens}
        if self.model:
            kwargs["model"] = self.model
        if self.expects_json:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self.llm.generate(
                messages=messages, temperature=self.temperature, **kwargs
            )
        except Exception as exc:  # noqa: BLE001 - provider errors become clean failures
            return {
                "status": "failure",
                "payload": None,
                "output": None,
                "error": f"{type(exc).__name__}: {exc}",
            }

        content = (response.get("content") or "").strip()
        telemetry = {
            "tokens": response.get("tokens"),
            "cost_usd": response.get("cost_usd"),
            "provider": response.get("provider"),
            "model": response.get("model"),
        }

        payload: Any = content
        if self.expects_json:
            parsed = _parse_json_object(content)
            if parsed is None:
                return {
                    "status": "failure",
                    "payload": None,
                    "output": content,
                    "error": "LLM did not return a parseable JSON object.",
                    **telemetry,
                }
            payload = parsed

        return {
            "status": "success",
            "payload": payload,
            "output": payload,
            "error": None,
            **telemetry,
        }

    async def on_peer_request(self, msg: Any) -> Dict[str, Any]:
        """Peer requests run the same single structured completion."""
        data = getattr(msg, "data", msg)
        task = data if isinstance(data, dict) else {"task": str(data)}
        return await self.execute_task(task)
