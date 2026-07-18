"""
jarviscore.orchestration.fanout
================================
Dynamic fan-out: run one task template over N runtime-determined items with
bounded concurrency, and aggregate the results explicitly (issue #52).

Where ``mesh.workflow()`` executes a DAG declared upfront, ``mesh.fanout()``
handles the map-shape that agent systems hit constantly — scan results, file
lists, symbol boards — where N is data, not authorship:

    result = await mesh.fanout(
        "board-scan",
        agent="analyst",
        items=symbols,
        task=lambda s: f"Deep-read {s} on H1 and return a thesis JSON.",
        context=lambda s: {"symbol": s},
        concurrency=5,
        budget=20,
    )
    theses = [r["payload"] for r in result.succeeded]

Design rules (learned in production, see #52/#53/#54):
- Identity by construction: every item runs under a namespaced workflow/step
  id and every result is stamped with ``item`` and ``step_id`` — concurrent
  items cannot cross-contaminate, and aggregation is by identity, not order
  guessing.
- Bounded concurrency and an optional item budget — fan-out without a
  ceiling is a cost and latency grenade.
- Partial failure is a first-class outcome: one bad item never voids the
  rest; ``.failed`` carries honest per-item errors.
- Aggregation is explicit and lossless by default: full results in item
  order; the reduce step is the caller's choice.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _slug(item: Any, index: int) -> str:
    """Stable, filesystem/redis-safe identity slug for one item."""
    text = _SLUG_RE.sub("-", str(item))[:48].strip("-") or "item"
    return f"{index:04d}-{text}"


@dataclass
class FanoutResult:
    """The outcome of one fan-out: full results in item order, plus views.

    Attributes:
        fanout_id: The id the fan-out ran under.
        results:   One result dict per attempted item, in ITEM ORDER. Every
                   dict carries ``item``, ``step_id``, and ``status``.
        skipped:   Items not attempted (budget cap), in item order.
        elapsed_ms: Wall time for the whole fan-out.
    """

    fanout_id: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[Any] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def succeeded(self) -> List[Dict[str, Any]]:
        """Results whose status is success, in item order."""
        return [r for r in self.results if r.get("status") == "success"]

    @property
    def failed(self) -> List[Dict[str, Any]]:
        """Results that errored, in item order — honest per-item errors."""
        return [r for r in self.results if r.get("status") != "success"]

    def aggregate(self, fn: Callable[[List[Dict[str, Any]]], Any]) -> Any:
        """Deterministic reduce over the SUCCESSFUL results."""
        return fn(self.succeeded)

    async def summarize(
        self,
        llm: Any,
        prompt: str,
        *,
        evidence_limit: int = 800,
    ) -> str:
        """LLM reduce: one completion over per-item evidence windows.

        Evidence follows the honest-context rules: each item contributes up
        to ``evidence_limit`` chars WITH an explicit truncation marker when
        clipped — a summarizer that cannot see the evidence confabulates
        (see #59). Failures are listed so the summary reflects reality.
        """
        lines: List[str] = []
        for r in self.succeeded:
            payload = r.get("payload", r.get("output"))
            text = str(payload)
            if len(text) > evidence_limit:
                text = (
                    f"{text[:evidence_limit]}"
                    f"…[truncated: showing {evidence_limit} of {len(text)} chars]"
                )
            lines.append(f"- {r['item']}: {text}")
        for r in self.failed:
            lines.append(f"- {r['item']}: FAILED — {str(r.get('error', 'unknown'))[:200]}")
        if self.skipped:
            lines.append(f"- ({len(self.skipped)} items skipped by budget: {self.skipped})")

        response = await llm.generate(
            messages=[{
                "role": "user",
                "content": f"{prompt}\n\nResults ({len(self.results)} items):\n" + "\n".join(lines),
            }]
        )
        return (response.get("content") or "").strip()

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe snapshot for logging/persistence."""
        return {
            "fanout_id": self.fanout_id,
            "total": len(self.results),
            "succeeded": len(self.succeeded),
            "failed": len(self.failed),
            "skipped": len(self.skipped),
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


async def run_fanout(
    *,
    fanout_id: str,
    find_agent: Callable[[Dict[str, Any]], Optional[Any]],
    agent: str,
    items: Iterable[Any],
    task: Union[str, Callable[[Any], str]],
    context: Optional[Union[Dict[str, Any], Callable[[Any], Dict[str, Any]]]] = None,
    concurrency: int = 5,
    budget: Optional[int] = None,
    on_error: str = "collect",
    timeout: Optional[float] = None,
) -> FanoutResult:
    """Execute one task template over N items with bounded concurrency.

    Args:
        fanout_id:   Unique id; namespaces every item's workflow/step ids.
        find_agent:  Resolver from a step spec to an agent (the mesh's claimer).
        agent:       Role or capability to execute each item.
        items:       The dynamic N. Materialized once; order defines result order.
        task:        Task string, or ``item -> str`` template.
        context:     Static dict, or ``item -> dict`` for per-item context.
        concurrency: Max items in flight (>=1). Fan-out is always bounded.
        budget:      Optional cap on items attempted; the rest are ``skipped``
                     honestly, never silently dropped.
        on_error:    "collect" (default): failures land in ``.failed`` and the
                     rest continue. "fail_fast": first failure cancels pending
                     items (already-finished results are kept).
        timeout:     Optional per-item timeout in seconds.

    Returns:
        FanoutResult — results in item order, each stamped with item + step_id.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    if on_error not in ("collect", "fail_fast"):
        raise ValueError('on_error must be "collect" or "fail_fast"')

    all_items = list(items)
    attempted = all_items if budget is None else all_items[:budget]
    skipped = [] if budget is None else all_items[budget:]

    semaphore = asyncio.Semaphore(concurrency)
    fail_fast_tripped = asyncio.Event()
    started = time.monotonic()

    async def _run_one(index: int, item: Any) -> Dict[str, Any]:
        step_id = f"{fanout_id}:{_slug(item, index)}"
        base: Dict[str, Any] = {
            "item": item,
            "step_id": step_id,
            "status": "failure",
        }
        if fail_fast_tripped.is_set():
            return {**base, "error": "cancelled: fail_fast tripped by an earlier item"}
        async with semaphore:
            if fail_fast_tripped.is_set():
                return {**base, "error": "cancelled: fail_fast tripped by an earlier item"}
            task_text = task(item) if callable(task) else str(task)
            item_ctx = dict(context(item)) if callable(context) else dict(context or {})
            item_ctx.setdefault("workflow_id", fanout_id)
            item_ctx["step_id"] = step_id
            item_ctx["fanout_item"] = item

            resolved = find_agent({"agent": agent, "task": task_text})
            if resolved is None:
                result = {**base, "error": f"No agent found for {agent!r}"}
            else:
                try:
                    coro = resolved.execute_task({"task": task_text, "context": item_ctx})
                    raw = await (asyncio.wait_for(coro, timeout) if timeout else coro)
                    if isinstance(raw, dict):
                        result = {**raw, **{k: base[k] for k in ("item", "step_id")}}
                        result.setdefault("status", "success")
                    else:
                        result = {**base, "status": "success", "output": raw}
                except asyncio.TimeoutError:
                    result = {**base, "error": f"timed out after {timeout}s"}
                except Exception as exc:  # noqa: BLE001 - per-item failures are data
                    result = {**base, "error": f"{type(exc).__name__}: {exc}"}

            if result.get("status") != "success" and on_error == "fail_fast":
                fail_fast_tripped.set()
            return result

    results = await asyncio.gather(
        *(_run_one(i, item) for i, item in enumerate(attempted))
    )

    outcome = FanoutResult(
        fanout_id=fanout_id,
        results=list(results),
        skipped=skipped,
        elapsed_ms=(time.monotonic() - started) * 1000,
    )
    logger.info("Fanout %s complete: %s", fanout_id, outcome.to_dict())
    return outcome
