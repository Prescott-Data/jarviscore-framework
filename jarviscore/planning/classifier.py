import json
from typing import Dict, Any, Optional

class ComplexityVerdict:
    def __init__(self, level: str, reason: str):
        self.level = level
        self.reason = reason

class ComplexityClassificationError(RuntimeError):
    """Raised when the complexity classifier cannot produce a valid verdict."""

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
            "Classify by execution shape, not prompt length. A long prompt that asks for "
            "one bounded answer, review, meeting contribution, JSON object, or artifact "
            "from supplied context is not complex just because it contains detailed instructions.\n"
            "If context_summary.execution_contract.execution_shape is single_response or "
            "single_artifact, treat it as a direct Kernel turn unless the task explicitly "
            "requires external research, browser/API work, code execution, or a multi-step workflow.\n\n"
            "- trivial: Can be answered or executed in ONE single step or API call. "
            "(e.g., 'Say hello', 'What is 2+2', 'Fetch user 123 profile')\n"
            "- moderate: Requires 2-3 logical steps but is straightforward.\n"
            "- complex: Requires significant planning, research, multiple subagents, or trial/error."
        )

    async def classify(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ComplexityVerdict:
        payload: Any = task
        if context:
            payload = {
                "task": task,
                "context_summary": self._summarize_context(context),
            }
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}
        ]

        try:
            result = await self.llm.generate(
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
        except TypeError:
            result = await self.llm.generate(messages=messages, temperature=0.0)
        except Exception as exc:
            raise ComplexityClassificationError(
                f"Complexity classifier LLM call failed: {exc}"
            ) from exc

        content = result.get("content", "{}").strip()
        start = content.find("{")
        end = content.rfind("}") + 1
        if start < 0 or end <= start:
            raise ComplexityClassificationError(
                f"Complexity classifier response is not JSON: {content[:300]}"
            )
        try:
            data = json.loads(content[start:end])
        except json.JSONDecodeError as exc:
            raise ComplexityClassificationError(
                f"Complexity classifier response is invalid JSON: {content[:300]}"
            ) from exc

        level = str(data.get("level", "")).lower().strip()
        if level not in {"trivial", "moderate", "complex"}:
            raise ComplexityClassificationError(
                f"Complexity classifier returned invalid level {level!r}"
            )
        return ComplexityVerdict(
            level=level,
            reason=str(data.get("reason", "")),
        )

    @staticmethod
    def _summarize_context(context: Dict[str, Any]) -> Dict[str, Any]:
        """Keep complexity routing focused on execution shape, not payload size."""
        summary: Dict[str, Any] = {}
        for key in ("complexity", "execution_contract", "meeting_step_id", "workflow_id", "step_id"):
            if key in context:
                summary[key] = context[key]
        if "previous_step_results" in context:
            previous = context.get("previous_step_results") or {}
            if isinstance(previous, dict):
                summary["previous_step_result_ids"] = list(previous.keys())[:20]
        return summary
