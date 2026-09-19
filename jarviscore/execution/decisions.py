"""Typed decision-model clients for machine-consumable judgments."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Optional

from jarviscore.orchestration.budget import current_workflow_budget


class DecisionClientError(RuntimeError):
    """Raised when a decision provider cannot evaluate a request."""


def _string_keyed(probabilities: Mapping[Any, Any]) -> dict[str, float]:
    return {str(key): float(value) for key, value in probabilities.items()}


@dataclass(frozen=True)
class DecisionResult:
    """JSON-safe TypeSafe System One response."""

    model: str
    answers: dict[str, dict[str, Any]]
    usage: dict[str, int]
    cost_usd: float
    request_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "answers": self.answers,
            "usage": self.usage,
            "cost_usd": self.cost_usd,
            "request_id": self.request_id,
        }


class JevDecisionClient:
    """Async client for TypeSafe Jev Choice, Score, and Noul decisions."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = "jev-latest",
        timeout: float = 10.0,
        base_url: Optional[str] = None,
        input_cost_per_million_usd: float = 0.042,
        client: Any = None,
    ) -> None:
        self.input_cost_per_million_usd = max(0.0, float(input_cost_per_million_usd))
        if client is not None:
            self._client = client
            return

        try:
            from typesafe_sdk import AsyncTypeSafeClient
        except ImportError as exc:
            raise DecisionClientError(
                'TypeSafe support requires `pip install "jarviscore-framework[typesafe]"`.'
            ) from exc

        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "model": model,
            "timeout": timeout,
        }
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncTypeSafeClient(**kwargs)

    async def evaluate(
        self,
        *,
        state: Any,
        questions: Mapping[str, Any],
        model: Optional[str] = None,
    ) -> DecisionResult:
        """Evaluate typed questions against text or structured state."""
        budget_account = current_workflow_budget()
        reservation_id = None
        if budget_account is not None:
            request_bytes = len(
                json.dumps(
                    {"state": state, "questions": questions},
                    ensure_ascii=False,
                    default=str,
                ).encode("utf-8")
            )
            reservation_id = budget_account.reserve(request_bytes + (256 * len(questions)))

        call_kwargs: dict[str, Any] = {
            "state": state,
            "questions": questions,
        }
        if model:
            call_kwargs["model"] = model
        try:
            response = await self._client.system_one(**call_kwargs)
        except BaseException as exc:
            if budget_account is not None and reservation_id is not None:
                budget_account.release(reservation_id)
            if not isinstance(exc, Exception):
                raise
            raise DecisionClientError(
                f"TypeSafe Jev decision failed ({type(exc).__name__})."
            ) from exc

        usage = response.usage
        input_tokens = int(usage.input_tokens or 0)
        output_tokens = int(usage.output_tokens or 0)
        cost_usd = input_tokens * self.input_cost_per_million_usd / 1_000_000
        if budget_account is not None and reservation_id is not None:
            budget_account.settle(
                reservation_id,
                input_tokens + output_tokens,
                cost_usd,
            )
        answers = {
            name: self._normalize_answer(answer) for name, answer in response.answers.items()
        }
        return DecisionResult(
            model=str(response.model),
            answers=answers,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            cost_usd=cost_usd,
            request_id=getattr(response, "request_id", None),
        )

    async def close(self) -> None:
        """Release the underlying SDK client."""
        close = getattr(self._client, "aclose", None)
        if callable(close):
            await close()

    @staticmethod
    def _normalize_answer(answer: Any) -> dict[str, Any]:
        answer_type = str(getattr(answer, "type", "")).lower()
        if hasattr(answer, "choice"):
            return {
                "type": answer_type or "choice",
                "choice": str(answer.choice),
                "probabilities": _string_keyed(answer.probabilities),
                "confidence": float(answer.confidence),
            }
        if hasattr(answer, "score"):
            # Score levels arrive as integer keys; JSON would convert them anyway,
            # so a checkpointed answer stays identical to the one just returned.
            return {
                "type": answer_type or "score",
                "score": float(answer.score),
                "legend": {str(level): text for level, text in answer.legend.items()},
                "probabilities": _string_keyed(answer.probabilities),
                "confidence": float(answer.confidence),
            }
        if hasattr(answer, "noul"):
            return {
                "type": answer_type or "noul",
                "noul": float(answer.noul),
            }
        raise DecisionClientError(f"Unsupported TypeSafe answer object: {type(answer).__name__}")


def create_decision_client(
    config: Optional[Mapping[str, Any]] = None,
) -> Optional[JevDecisionClient]:
    """Create the configured TypeSafe client, or return None when disabled."""
    from jarviscore.config import settings

    resolved = settings.model_dump()
    if config:
        resolved.update(config)
    api_key = resolved.get("typesafe_api_key")
    if not api_key:
        return None
    return JevDecisionClient(
        api_key=str(api_key),
        model=str(resolved.get("typesafe_model") or "jev-latest"),
        timeout=float(resolved.get("typesafe_timeout") or 10.0),
        base_url=resolved.get("typesafe_base_url"),
        input_cost_per_million_usd=float(
            resolved.get("typesafe_input_cost_per_million_usd") or 0.042
        ),
    )
