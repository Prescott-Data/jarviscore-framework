"""
jarviscore.orchestration.workflow_builder
==========================================
WorkflowBuilder — lets agents compose structured DAG workflows programmatically.

The Redis DAG infrastructure (init_workflow_graph, claim_step, update_step_status,
are_dependencies_met) already exists in RedisContextStore. WorkflowBuilder gives
agents a fluent API to compose and register DAGs, replacing the ad-hoc JSON
synthesis that previously happened inside execute_autonomous_backlog().

Usage (inside any agent):

    from jarviscore.orchestration.workflow_builder import WorkflowBuilder

    wf = (
        WorkflowBuilder()
        .step("research", "researcher", "Gather market data on topic X")
        .step("analyse",  "analyst",    "Analyse findings: {research.result}", depends_on=["research"])
        .step("draft",    "writer",     "Draft report from: {analyse.result}", depends_on=["analyse"])
        .step("review",   "reviewer",   "QA the draft for accuracy",           depends_on=["draft"])
        .build(title="Research-to-report pipeline", team="my-team")
    )

    workflow_id = await wf.register(redis_store)
    results = await wf.execute(mesh)

Design:
  - Steps are lightweight dicts — no LLM calls at construction time
  - Dependency resolution is topological (handled by RedisContextStore)
  - Result variables (e.g., {intel.result}) are resolved at execution time
    by substituting prior step outputs into task descriptions
  - Fully compatible with the existing mesh.workflow() execution path
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorkflowStep:
    """A single step in a workflow DAG."""

    def __init__(
        self,
        step_id: str,
        agent: str,
        task: str,
        depends_on: Optional[List[str]] = None,
    ) -> None:
        self.step_id = step_id
        self.agent = agent
        self.task = task
        self.depends_on: List[str] = depends_on or []
        self.result: Optional[Any] = None
        self.status: str = "pending"

    def to_dict(self) -> Dict:
        return {
            "id": self.step_id,
            "agent": self.agent,
            "task": self.task,
            "depends_on": self.depends_on,
            "status": self.status,
        }

    def resolve_task(self, step_results: Dict[str, Any]) -> str:
        """
        Substitute {step_id.result} placeholders with actual prior results.

        Allows steps to reference the output of upstream steps:
            "Draft post on: {intel.result}"
        """
        def _replace(match: re.Match) -> str:
            ref_step = match.group(1)
            ref_field = match.group(2)
            if ref_step in step_results and ref_field == "result":
                val = step_results[ref_step]
                if isinstance(val, dict):
                    return str(val.get("output") or val.get("result") or val)
                return str(val)[:500]
            return match.group(0)  # leave unresolved placeholders as-is

        return re.sub(r"\{(\w+)\.(\w+)\}", _replace, self.task)


class Workflow:
    """
    A composed, registerable DAG workflow.

    Created by WorkflowBuilder.build(). Holds all steps and metadata.
    Call register() to persist to Redis, then execute() to run.
    """

    def __init__(
        self,
        steps: List[WorkflowStep],
        title: str = "",
        team: str = "",
        workflow_id: Optional[str] = None,
    ) -> None:
        self.steps = steps
        self.title = title
        self.team = team
        self.workflow_id = workflow_id or f"wf-{uuid.uuid4().hex[:10]}"
        self.created_at = time.time()
        self._registered = False

    # ── Registration ─────────────────────────────────────────────────────────

    async def register(self, redis_store=None) -> str:
        """
        Persist this workflow's DAG to Redis.

        Args:
            redis_store: RedisContextStore instance. If None, workflow runs in-memory only.

        Returns:
            workflow_id for tracking.
        """
        if redis_store:
            try:
                redis_store.init_workflow_graph(
                    self.workflow_id,
                    [s.to_dict() for s in self.steps],
                )
                redis_store.register_active_workflow(self.workflow_id)
                self._registered = True
                logger.info(
                    "[Workflow] Registered '%s' (%s) with %d steps",
                    self.title or self.workflow_id,
                    self.workflow_id,
                    len(self.steps),
                )
            except Exception as exc:
                logger.warning("[Workflow] Redis registration failed (non-fatal): %s", exc)
        return self.workflow_id

    # ── Execution ─────────────────────────────────────────────────────────────

    async def execute(
        self,
        mesh,
        redis_store=None,
        timeout_per_step: int = 300,
    ) -> List[Dict[str, Any]]:
        """
        Execute the workflow DAG by dispatching steps to agents via mesh.

        Steps are executed in topological order (respecting depends_on).
        Each step's output is available to downstream steps via {step_id.result}.

        Args:
            mesh: JarvisCore Mesh instance for agent dispatching
            redis_store: Optional — updates step status in Redis as we go
            timeout_per_step: Max seconds per step before considering it timed out

        Returns:
            List of dicts: [{step_id, agent, status, output, error, elapsed_ms}]
        """
        results: Dict[str, Any] = {}
        execution_log: List[Dict] = []
        pending = list(self.steps)

        if not pending:
            return []

        logger.info("[Workflow] Executing '%s' (%d steps)", self.title or self.workflow_id, len(pending))

        # Topological execution: poll until all steps done or max iterations
        max_rounds = len(pending) * 2
        round_num = 0

        while pending and round_num < max_rounds:
            round_num += 1
            ready = []
            still_pending = []

            for step in pending:
                # Check dependencies satisfied
                all_deps_done = all(
                    dep in results and results[dep].get("status") == "success"
                    for dep in step.depends_on
                )
                if all_deps_done:
                    ready.append(step)
                else:
                    still_pending.append(step)

            if not ready:
                logger.warning("[Workflow] No steps ready — possible cycle or blocked deps. Stopping.")
                break

            # Execute all ready steps (can be parallel if no deps between them)
            async def _run_step(step: WorkflowStep) -> Dict:
                t0 = time.time()
                resolved_task = step.resolve_task(results)
                logger.info("[Workflow] Dispatching step=%s agent=%s", step.step_id, step.agent)

                if redis_store:
                    try:
                        redis_store.update_step_status(self.workflow_id, step.step_id, "in_progress")
                    except Exception as exc:
                        logger.warning(
                            "[Workflow] Failed to persist in_progress for step %s: %s",
                            step.step_id,
                            exc,
                        )

                try:
                    result = await asyncio.wait_for(
                        mesh.run_task(
                            agent_role=step.agent,
                            task=resolved_task,
                            context={"workflow_id": self.workflow_id, "step_id": step.step_id},
                        ),
                        timeout=timeout_per_step,
                    )
                    result_status = result.get("status") if isinstance(result, dict) else "success"
                    if result_status == "success":
                        step.status = "success"
                        step.result = result
                        output = result
                        error = None
                    else:
                        step.status = str(result_status or "failure")
                        step.result = None
                        output = None
                        error = (
                            result.get("error")
                            or result.get("summary")
                            or f"Step ended with status={result_status!r}"
                            if isinstance(result, dict)
                            else f"Step returned invalid status={result_status!r}"
                        )
                    entry = {
                        "step_id": step.step_id,
                        "agent": step.agent,
                        "status": step.status,
                        "output": output,
                        "error": error,
                        "elapsed_ms": round((time.time() - t0) * 1000),
                    }
                except asyncio.TimeoutError:
                    step.status = "timeout"
                    entry = {
                        "step_id": step.step_id,
                        "agent": step.agent,
                        "status": "timeout",
                        "output": None,
                        "error": f"Step timed out after {timeout_per_step}s",
                        "elapsed_ms": round((time.time() - t0) * 1000),
                    }
                except Exception as exc:
                    step.status = "failure"
                    entry = {
                        "step_id": step.step_id,
                        "agent": step.agent,
                        "status": "failure",
                        "output": None,
                        "error": str(exc),
                        "elapsed_ms": round((time.time() - t0) * 1000),
                    }

                if redis_store:
                    try:
                        redis_store.update_step_status(self.workflow_id, step.step_id, step.status)
                    except Exception as exc:
                        logger.warning(
                            "[Workflow] Failed to persist final status for step %s: %s",
                            step.step_id,
                            exc,
                        )

                logger.info(
                    "[Workflow] Step %s: %s (%dms)",
                    step.step_id, step.status, entry["elapsed_ms"]
                )
                return entry

            step_results = await asyncio.gather(*[_run_step(s) for s in ready])

            for entry, step in zip(step_results, ready):
                results[step.step_id] = entry
                execution_log.append(entry)

            pending = still_pending

        if pending:
            logger.warning(
                "[Workflow] %d steps did not execute: %s",
                len(pending), [s.step_id for s in pending]
            )

        logger.info("[Workflow] '%s' complete: %d/%d steps successful",
                    self.title or self.workflow_id,
                    sum(1 for e in execution_log if e["status"] == "success"),
                    len(self.steps))
        return execution_log

    def to_dict(self) -> Dict:
        return {
            "workflow_id": self.workflow_id,
            "title": self.title,
            "team": self.team,
            "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
        }


class WorkflowBuilder:
    """
    Fluent builder API for composing workflow DAGs.

    Example:
        wf = (
            WorkflowBuilder()
            .step("research", "researcher", "Gather latest data on topic X")
            .step("draft",    "writer",     "Draft report from: {research.result}", depends_on=["research"])
            .step("review",   "reviewer",   "QA the draft",                         depends_on=["draft"])
            .build(title="Research pipeline", team="my-team")
        )
        workflow_id = await wf.register(redis_store)
        results = await wf.execute(mesh)
    """

    def __init__(self) -> None:
        self._steps: List[WorkflowStep] = []
        self._step_ids: set = set()

    def step(
        self,
        step_id: str,
        agent: str,
        task: str,
        depends_on: Optional[List[str]] = None,
    ) -> "WorkflowBuilder":
        """
        Add a step to the workflow.

        Args:
            step_id:    Unique step identifier (used for {step_id.result} references)
            agent:      Agent role to dispatch this step to (e.g., "researcher", "writer")
            task:       Natural language task description. Can reference prior step results
                        using {step_id.result} syntax.
            depends_on: List of step_ids that must succeed before this step runs.

        Returns:
            self (for chaining)
        """
        if step_id in self._step_ids:
            raise ValueError(f"Duplicate step_id: '{step_id}'. Step IDs must be unique.")

        deps = depends_on or []
        for dep in deps:
            if dep not in self._step_ids:
                raise ValueError(
                    f"Step '{step_id}' depends on '{dep}' which hasn't been defined yet. "
                    "Define steps in topological order."
                )

        self._steps.append(WorkflowStep(step_id=step_id, agent=agent, task=task, depends_on=deps))
        self._step_ids.add(step_id)
        return self

    def build(self, title: str = "", team: str = "") -> Workflow:
        """
        Build and return the Workflow object (does not register or execute yet).

        Args:
            title: Human-readable workflow name (shown in dashboard)
            team:  Optional team identifier for grouping workflows

        Returns:
            Workflow instance ready for register() and execute()
        """
        if not self._steps:
            raise ValueError("Cannot build an empty workflow. Add at least one step first.")

        return Workflow(
            steps=list(self._steps),
            title=title,
            team=team,
        )
