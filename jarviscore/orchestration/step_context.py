"""
The mesh step running right now.

The Mesh sets it while an agent executes a step, so anything the step creates
along the way, such as a question for a person, can say which work it belongs
to, and the work can be resumed once it is answered.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional, Tuple

current_step: ContextVar[Optional[Tuple[str, str]]] = ContextVar("jarviscore_current_step", default=None)


@contextmanager
def in_step(workflow_id: str, step_id: str) -> Iterator[None]:
    token = current_step.set((str(workflow_id), str(step_id)))
    try:
        yield
    finally:
        current_step.reset(token)
