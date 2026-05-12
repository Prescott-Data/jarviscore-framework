import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ComplexityVerdict:
    def __init__(self, level: str, reason: str):
        self.level = level
        self.reason = reason

class TaskComplexityClassifier:
    """
    Cognitive router that gates tasks before the full Planner DAG.
    Classifies tasks as 'trivial', 'moderate', or 'complex'.
    """
    def __init__(self, llm_client):
        self.llm = llm_client
        self.system_prompt = (
            "You are a cognitive router for a multi-agent framework. "
            "Your job is to classify the complexity of a user's task to determine "
            "if it needs a full multi-step execution plan or can be solved in a single step.\n\n"
            "Respond ONLY with a JSON object:\n"
            "{\n"
            "  \"level\": \"trivial\" | \"moderate\" | \"complex\",\n"
            "  \"reason\": \"Brief explanation\"\n"
            "}\n\n"
            "- trivial: Can be answered or executed in ONE single step or API call. "
            "(e.g., 'Say hello', 'What is 2+2', 'Fetch user 123 profile')\n"
            "- moderate: Requires 2-3 logical steps but is straightforward.\n"
            "- complex: Requires significant planning, research, multiple subagents, or trial/error."
        )

    async def classify(self, task: str) -> ComplexityVerdict:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task}
        ]

        try:
            result = await self.llm.generate(messages=messages, temperature=0.0)
            content = result.get("content", "{}").strip()

            # Simple extraction of JSON
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
                return ComplexityVerdict(
                    level=data.get("level", "moderate").lower(),
                    reason=data.get("reason", "Parsed correctly")
                )
        except Exception as e:
            logger.warning(f"Complexity classification failed, defaulting to moderate: {e}")

        return ComplexityVerdict(level="moderate", reason="Fallback due to error")
