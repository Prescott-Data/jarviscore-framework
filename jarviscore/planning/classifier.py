import json
import logging
from typing import Dict, Any, Optional

from jarviscore.orchestration.budget import WorkflowBudgetExceeded

logger = logging.getLogger(__name__)

class ComplexityVerdict:
    def __init__(
        self,
        level: str,
        reason: str,
        *,
        confidence: float = 1.0,
        provider: str = "contract",
        probabilities: Optional[Dict[str, float]] = None,
        request_id: Optional[str] = None,
        model: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
        cost_usd: float = 0.0,
    ):
        self.level = level
        self.reason = reason
        self.confidence = confidence
        self.provider = provider
        self.probabilities = probabilities or {}
        self.request_id = request_id
        self.model = model
        self.usage = usage or {}
        self.cost_usd = cost_usd

class ComplexityClassificationError(RuntimeError):
    """Raised when the complexity classifier cannot produce a valid verdict."""

class TaskComplexityClassifier:
    """
    Cognitive router that gates tasks before the full Planner DAG.
    Classifies tasks as 'trivial', 'moderate', or 'complex'.
    """
    def __init__(
        self,
        llm_client,
        *,
        decision_client=None,
        provider: str = "llm",
        min_confidence: float = 0.5,
    ):
        self.llm = llm_client
        self.decision_client = decision_client
        self.provider = str(provider).lower()
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        if self.provider not in {"llm", "typesafe"}:
            raise ValueError("task_complexity_provider must be either 'llm' or 'typesafe'")
        if self.provider == "typesafe" and self.decision_client is None:
            raise ValueError(
                "task_complexity_provider='typesafe' requires TYPESAFE_API_KEY "
                'and the `jarviscore-framework[typesafe]` extra'
            )
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
        if self.provider == "typesafe":
            try:
                return await self._classify_with_typesafe(task, context)
            except WorkflowBudgetExceeded:
                raise
            except Exception as exc:
                logger.warning(
                    "TypeSafe complexity classification failed; using the existing LLM classifier: %s",
                    exc,
                )
        return await self._classify_with_llm(task, context)

    async def _classify_with_typesafe(
        self,
        task: str,
        context: Optional[Dict[str, Any]],
    ) -> ComplexityVerdict:
        result = await self.decision_client.evaluate(
            state={
                "task": task,
                "context_summary": self._summarize_context(context or {}),
            },
            questions={
                "complexity": {
                    "type": "choice",
                    "instructions": "What execution shape does this task require?",
                    "criteria": {
                        "trivial": (
                            "One bounded answer or one API call; no planning or trial and error."
                        ),
                        "moderate": (
                            "Two or three straightforward operations, or one bounded artifact."
                        ),
                        "complex": (
                            "Significant planning, research, multiple specialists, verification, "
                            "or trial and error."
                        ),
                    },
                }
            },
        )
        answer = result.answers.get("complexity") or {}
        level = str(answer.get("choice") or "").lower().strip()
        if level not in {"trivial", "moderate", "complex"}:
            raise ComplexityClassificationError(
                f"TypeSafe complexity classifier returned invalid level {level!r}"
            )
        confidence = max(0.0, min(1.0, float(answer.get("confidence") or 0.0)))
        probabilities = {
            str(name): float(probability)
            for name, probability in (answer.get("probabilities") or {}).items()
        }
        if confidence < self.min_confidence:
            return ComplexityVerdict(
                level="complex",
                reason=(
                    f"TypeSafe complexity confidence {confidence:.2f} is below "
                    f"{self.min_confidence:.2f}; preserving the planning path."
                ),
                confidence=confidence,
                provider="typesafe",
                probabilities=probabilities,
                request_id=result.request_id,
                model=result.model,
                usage=dict(result.usage),
                cost_usd=float(result.cost_usd),
            )
        return ComplexityVerdict(
            level=level,
            reason="TypeSafe Jev classified the task execution shape.",
            confidence=confidence,
            provider="typesafe",
            probabilities=probabilities,
            request_id=result.request_id,
            model=result.model,
            usage=dict(result.usage),
            cost_usd=float(result.cost_usd),
        )

    async def _classify_with_llm(
        self,
        task: str,
        context: Optional[Dict[str, Any]],
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
            provider="llm",
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
