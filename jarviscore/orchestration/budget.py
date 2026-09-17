"""Workflow-global execution budget scope for every LLM call."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Optional
from uuid import uuid4


class WorkflowBudgetExceeded(RuntimeError):
    """Raised before an LLM call when its workflow cannot reserve capacity."""


@dataclass(frozen=True)
class WorkflowBudgetAccount:
    store: Any
    workflow_id: str
    epoch_id: str

    def reserve(self, tokens: int) -> str:
        reservation_id = uuid4().hex
        if not self.store.reserve_workflow_tokens(
            self.workflow_id,
            self.epoch_id,
            reservation_id,
            max(1, int(tokens)),
        ):
            usage = self.store.get_workflow_budget_usage(self.workflow_id) or {}
            raise WorkflowBudgetExceeded(
                f"Workflow {self.workflow_id!r} cannot reserve {tokens} tokens; "
                f"epoch={self.epoch_id!r}, "
                f"epoch_used={usage.get('epoch_used_tokens', 0)}, "
                f"epoch_reserved={usage.get('epoch_reserved_tokens', 0)}, "
                f"epoch_limit={usage.get('max_tokens_per_epoch', 0)}."
            )
        return reservation_id

    def settle(self, reservation_id: str, tokens: int, cost_usd: float) -> None:
        self.store.settle_workflow_tokens(
            self.workflow_id,
            self.epoch_id,
            reservation_id,
            max(0, int(tokens)),
            max(0.0, float(cost_usd)),
        )

    def release(self, reservation_id: str) -> None:
        self.store.release_workflow_token_reservation(
            self.workflow_id,
            self.epoch_id,
            reservation_id,
        )


_CURRENT_WORKFLOW_BUDGET: ContextVar[Optional[WorkflowBudgetAccount]] = ContextVar(
    "jarviscore_workflow_budget",
    default=None,
)


def current_workflow_budget() -> Optional[WorkflowBudgetAccount]:
    return _CURRENT_WORKFLOW_BUDGET.get()


@contextmanager
def workflow_budget_scope(
    store: Any,
    workflow_id: str,
    epoch_id: str = "default",
) -> Iterator[None]:
    token = _CURRENT_WORKFLOW_BUDGET.set(
        WorkflowBudgetAccount(
            store=store,
            workflow_id=workflow_id,
            epoch_id=epoch_id,
        )
    )
    try:
        yield
    finally:
        _CURRENT_WORKFLOW_BUDGET.reset(token)