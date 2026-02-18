"""
WorkflowEngine - Orchestrates multi-step workflow execution.

Phase 7B upgrade: Sequential per-step loop replaced by a sovereign reactive
loop (IA/CA pattern). Steps launch the moment their dependencies are met,
not in batches — so step C can start as soon as B finishes even if B's
peers are still running.

Reactive loop iteration:
    HARVEST  — collect any tasks that completed this tick
    DECIDE   — find every pending step whose deps are now satisfied
    ACT      — launch each claimable step as an asyncio.Task
    PERSIST  — save WorkflowState to Redis (crash recovery)
    PACE     — asyncio.wait(FIRST_COMPLETED, timeout=1.0) or sleep(0.5)

Crash recovery: on execute() check Redis for an existing WorkflowState.
If found and not complete, resume from where we left off (zombie steps
cleared, completed step outputs reloaded from Redis).
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set

from .claimer import StepClaimer
from .dependency import DependencyManager
from .state import WorkflowState
from .status import StatusManager, StepStatus
from jarviscore.context import create_context

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Executes multi-step workflows with dependency management.

    Phase 7B: Sovereign reactive loop replaces the old sequential loop.
    Steps that have no outstanding dependencies launch immediately and
    run concurrently. WorkflowState is persisted to Redis each iteration
    for crash recovery.

    The engine is backward-compatible: the public API (execute, get_status,
    get_memory) is unchanged. redis_store is optional — when absent the
    engine operates fully in-memory as before.
    """

    def __init__(
        self,
        mesh,
        p2p_coordinator=None,
        config: Optional[Dict] = None,
        redis_store=None,
    ):
        self.mesh = mesh
        self.p2p = p2p_coordinator
        self.config = config or {}
        self.redis_store = redis_store  # Phase 7: optional Redis backing

        # Core components
        self.claimer = StepClaimer(mesh.agents)
        self.status_manager = StatusManager()

        # Working memory (step_id → result)
        self.memory: Dict[str, Any] = {}
        self.dependency_manager = DependencyManager(
            self.memory, redis_store=redis_store
        )

        self._started = False
        logger.info("Workflow engine initialized")

    async def start(self):
        """Start the workflow engine."""
        if self._started:
            logger.warning("Workflow engine already started")
            return
        self._started = True
        logger.info("Workflow engine started")

    async def stop(self):
        """Stop the workflow engine and clear in-memory state."""
        if not self._started:
            return
        self._started = False
        self.memory.clear()
        self.status_manager.clear()
        logger.info("Workflow engine stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        workflow_id: str,
        steps: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Execute a multi-step workflow.

        Args:
            workflow_id: Unique workflow identifier (used for Redis keys and
                         crash recovery).
            steps: List of step specifications:
                [
                    {
                        "id":         "step1",              # optional, auto-generated
                        "agent":      "role_or_capability",
                        "task":       "Task description",
                        "depends_on": []                    # optional
                    }
                ]

        Returns:
            List of result dicts in original step order.
            Each result has at minimum a "status" key:
              "success" / "failure" / "waiting" / "skipped"

        The workflow returns even if some steps fail or wait — individual
        step status indicates what happened to each.
        """
        if not self._started:
            raise RuntimeError("Workflow engine not started. Call start() first.")

        logger.info(f"Executing workflow {workflow_id} with {len(steps)} step(s)")

        normalized = self._normalize_steps(steps)

        # ── Crash recovery ──────────────────────────────────────────
        if self.redis_store:
            raw = self.redis_store.load_workflow_state(workflow_id)
            if raw:
                try:
                    existing = WorkflowState.from_dict(json.loads(raw))
                    if not existing.is_complete():
                        logger.info(
                            f"Resuming workflow {workflow_id} from checkpoint "
                            f"({len(existing.processed_steps)} steps already done)"
                        )
                        return await self._resume(existing, normalized)
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    logger.warning(
                        f"Corrupt workflow state for {workflow_id}, starting fresh: {exc}"
                    )

        # ── Fresh start ──────────────────────────────────────────────
        if self.redis_store:
            self.redis_store.init_workflow_graph(workflow_id, normalized)

        state = WorkflowState(
            workflow_id=workflow_id,
            total_steps=len(normalized),
            status="running",
        )
        self._save_state(state)

        return await self._run_reactive_loop(workflow_id, normalized, state)

    # ------------------------------------------------------------------
    # Reactive Loop (Phase 7B core)
    # ------------------------------------------------------------------

    async def _run_reactive_loop(
        self,
        workflow_id: str,
        steps: List[Dict[str, Any]],
        state: WorkflowState,
    ) -> List[Dict[str, Any]]:
        """
        Sovereign reactive loop adapted from IA/CA production pattern.

        Unlike asyncio.gather() over dependency layers, this loop lets each
        step start the instant its dependencies complete, giving maximum
        parallelism on uneven workloads.
        """
        step_map = {s["id"]: s for s in steps}
        pending: Set[str] = set(step_map.keys())
        running_tasks: Dict[str, asyncio.Task] = {}
        results: Dict[str, Any] = {}

        # ── Zombie detection (crash recovery path) ───────────────────
        if state.running_steps:
            zombie_count = len(state.running_steps)
            logger.warning(
                f"{zombie_count} zombie step(s) detected in {workflow_id} "
                f"(crashed mid-run) — clearing for re-evaluation"
            )
            state.running_steps.clear()

        # Remove already-terminal steps from pending
        pending -= state.processed_steps
        pending -= state.failed_steps
        pending -= set(state.waiting_steps.keys())

        while pending or running_tasks:

            # ── HARVEST ──────────────────────────────────────────────
            done_ids = [sid for sid, t in running_tasks.items() if t.done()]
            for step_id in done_ids:
                task = running_tasks.pop(step_id)
                state.running_steps.pop(step_id, None)

                try:
                    result = task.result()
                except Exception as exc:
                    logger.error(f"Step {step_id} raised: {exc}", exc_info=True)
                    result = {
                        "status": "failure",
                        "error": str(exc),
                        "step_id": step_id,
                    }

                self._record_result(workflow_id, step_id, result, state, pending)
                results[step_id] = result

            # ── DECIDE ───────────────────────────────────────────────
            launchable = []
            for step_id in list(pending):
                if step_id in running_tasks:
                    continue
                step = step_map[step_id]
                dep_ids = self._resolve_dependency_ids(
                    step.get("depends_on", []), steps
                )
                if self._deps_met(dep_ids, state, workflow_id):
                    launchable.append(step)

            # ── ACT ──────────────────────────────────────────────────
            for step in launchable:
                step_id = step["id"]
                dep_ids = self._resolve_dependency_ids(
                    step.get("depends_on", []), steps
                )
                dep_outputs = {d: self.memory.get(d) for d in dep_ids}

                self.status_manager.update(step_id, StepStatus.IN_PROGRESS.value)
                if self.redis_store:
                    self.redis_store.update_step_status(
                        workflow_id, step_id, "in_progress"
                    )

                state.running_steps[step_id] = time.time()
                task = asyncio.create_task(
                    self._execute_step(workflow_id, step, dep_outputs),
                    name=f"step-{step_id}",
                )
                running_tasks[step_id] = task
                logger.info(f"Launched step {step_id}")

            # ── PERSIST ──────────────────────────────────────────────
            self._save_state(state)

            # ── DEADLOCK DETECTION ───────────────────────────────────
            if not running_tasks and pending:
                unblocked = any(
                    self._deps_met(
                        self._resolve_dependency_ids(
                            step_map[sid].get("depends_on", []), steps
                        ),
                        state,
                        workflow_id,
                    )
                    for sid in pending
                )
                if not unblocked:
                    logger.error(
                        f"Deadlock in {workflow_id}: steps {pending} cannot be satisfied"
                    )
                    for sid in list(pending):
                        state.failed_steps.add(sid)
                        results[sid] = {
                            "status": "failure",
                            "error": "dependency deadlock — dependencies will never complete",
                            "step_id": sid,
                        }
                        pending.discard(sid)
                    break

            # ── PACE ─────────────────────────────────────────────────
            if running_tasks:
                try:
                    await asyncio.wait(
                        running_tasks.values(),
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=1.0,
                    )
                except Exception:
                    await asyncio.sleep(0.5)
            elif pending:
                await asyncio.sleep(0.5)

        # ── Finalise workflow status ──────────────────────────────────
        if state.waiting_steps:
            state.status = "waiting"
        elif state.failed_steps:
            state.status = "failed"
        else:
            state.status = "completed"

        self._save_state(state)
        logger.info(
            f"Workflow {workflow_id} {state.status}: "
            f"{len(state.processed_steps)} done, "
            f"{len(state.failed_steps)} failed, "
            f"{len(state.waiting_steps)} waiting"
        )

        # Return in original step order
        return [
            results.get(s["id"], {"status": "skipped", "step_id": s["id"]})
            for s in steps
        ]

    # ------------------------------------------------------------------
    # Crash Recovery
    # ------------------------------------------------------------------

    async def _resume(
        self,
        state: WorkflowState,
        steps: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Resume a partially-completed workflow after crash/restart.

        Reloads completed step outputs from Redis into local memory so
        downstream steps can access them, then hands off to the reactive
        loop with the restored state.
        """
        logger.info(
            f"Resuming {state.workflow_id}: "
            f"{len(state.processed_steps)} done, "
            f"{len(state.failed_steps)} failed, "
            f"{len(state.waiting_steps)} waiting"
        )

        # Reload completed outputs into memory
        for step_id in state.processed_steps:
            if step_id not in self.memory and self.redis_store:
                saved = self.redis_store.get_step_output(state.workflow_id, step_id)
                if saved:
                    self.memory[step_id] = saved.get("output", saved)

        return await self._run_reactive_loop(state.workflow_id, steps, state)

    # ------------------------------------------------------------------
    # Step Execution
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        workflow_id: str,
        step: Dict[str, Any],
        dep_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single step and return its result dict."""
        step_id = step["id"]

        # Find agent
        agent = self.claimer.find_agent(step)
        if not agent:
            return {
                "status": "failure",
                "error": f"No agent found for step {step_id} "
                         f"(requirement: {step.get('agent')})",
                "step_id": step_id,
            }

        logger.info(f"Step {step_id} claimed by {agent.agent_id}")

        # Build task dict with dependency context
        task = step.copy()
        task["context"] = {
            "previous_step_results": dep_outputs,
            "workflow_id": workflow_id,
            "step_id": step_id,
        }

        # Auth resolution (Phase 7D)
        auth_manager = getattr(self.mesh, "_auth_manager", None)
        if auth_manager and getattr(agent, "requires_auth", False):
            auth_context = await self._resolve_auth(auth_manager, agent, step)
            if auth_context:
                task["context"]["auth_context"] = auth_context

        # Build JarvisContext for CustomAgent profiles
        jarvis_ctx = create_context(
            workflow_id=workflow_id,
            step_id=step_id,
            task=task.get("task", ""),
            params=task.get("params", {}),
            memory_dict=self.memory,
            dependency_manager=self.dependency_manager,
        )
        task["_jarvis_context"] = jarvis_ctx

        # Execute
        try:
            result = await agent.execute_task(task)
        except Exception as exc:
            logger.error(f"Step {step_id} agent raised: {exc}", exc_info=True)
            return {"status": "failure", "error": str(exc), "step_id": step_id}

        if isinstance(result, dict) and "agent" not in result:
            result["agent"] = agent.agent_id

        # P2P broadcast (best-effort, never fails the step)
        if self.p2p and hasattr(self.p2p, "broadcaster"):
            try:
                await self.p2p.broadcaster.broadcast_step_result(
                    step_id=step_id,
                    workflow_id=workflow_id,
                    output_data=result,
                    status="success",
                )
            except Exception as err:
                logger.warning(f"Broadcast failed for {step_id}: {err}")

        return result

    # ------------------------------------------------------------------
    # Auth Resolution (Phase 7D)
    # ------------------------------------------------------------------

    async def _resolve_auth(self, auth_manager, agent, step: Dict) -> Optional[Dict]:
        """
        Resolve auth context for an agent that declares requires_auth = True.

        Inspects the agent's code_registry for system dependencies in the
        step task text, then fetches credentials via AuthenticationManager.
        Returns None if no auth is needed or the agent has no code_registry.
        """
        code_registry = getattr(agent, "code_registry", None)
        if not code_registry:
            return None

        task_text = step.get("task", "")
        systems = code_registry.detect_system_dependencies(task_text)
        for system in systems:
            try:
                auth_ctx = await auth_manager.resolve_auth_context(
                    system, code_registry
                )
                if auth_ctx:
                    return auth_ctx
            except Exception as exc:
                logger.warning(f"Auth resolution failed for system {system}: {exc}")
        return None

    # ------------------------------------------------------------------
    # Dependency Helpers
    # ------------------------------------------------------------------

    def _deps_met(
        self,
        dep_ids: List[str],
        state: WorkflowState,
        workflow_id: str,
    ) -> bool:
        """
        Return True when every listed dependency is completed.

        Uses Redis DAG when available (authoritative across agents),
        falls back to local WorkflowState for in-memory-only mode.
        """
        if not dep_ids:
            return True

        if self.redis_store:
            return all(
                self.redis_store.get_step_status(workflow_id, dep_id) == "completed"
                for dep_id in dep_ids
            )

        return all(dep_id in state.processed_steps for dep_id in dep_ids)

    def _record_result(
        self,
        workflow_id: str,
        step_id: str,
        result: Dict[str, Any],
        state: WorkflowState,
        pending: Set[str],
    ) -> None:
        """Classify a step result and update state + Redis accordingly."""
        status = result.get("status") if isinstance(result, dict) else None

        if status == "waiting":
            reason = result.get("reason", "HITL")
            state.waiting_steps[step_id] = reason
            self.status_manager.update(step_id, StepStatus.WAITING.value)
            if self.redis_store:
                self.redis_store.update_step_status(workflow_id, step_id, "waiting")
            logger.info(f"Step {step_id} waiting: {reason}")

        elif status == "failure":
            state.failed_steps.add(step_id)
            self.status_manager.update(
                step_id, StepStatus.FAILED.value, error=result.get("error")
            )
            if self.redis_store:
                self.redis_store.update_step_status(workflow_id, step_id, "failed")
            logger.warning(f"Step {step_id} failed: {result.get('error')}")

        else:
            state.processed_steps.add(step_id)
            self.memory[step_id] = result
            self.status_manager.update(
                step_id, StepStatus.COMPLETED.value, output=result
            )
            if self.redis_store:
                self.redis_store.update_step_status(workflow_id, step_id, "completed")
                self.redis_store.save_step_output(
                    workflow_id, step_id, output=result
                )
            logger.info(f"Step {step_id} completed")

        pending.discard(step_id)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self, state: WorkflowState) -> None:
        """Persist WorkflowState to Redis for crash recovery."""
        if self.redis_store:
            self.redis_store.save_workflow_state(
                state.workflow_id, json.dumps(state.to_dict())
            )

    # ------------------------------------------------------------------
    # Step Normalisation & Dependency ID Resolution
    # ------------------------------------------------------------------

    def _normalize_steps(
        self, steps: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Ensure every step has an id field."""
        normalized = []
        for i, step in enumerate(steps):
            if "id" not in step:
                step = step.copy()
                step["id"] = f"step{i}"
            normalized.append(step)
        return normalized

    def _resolve_dependency_ids(
        self,
        depends_on: List,
        steps: List[Dict[str, Any]],
    ) -> List[str]:
        """Convert integer indices or string IDs to step ID strings."""
        dep_ids = []
        for dep in depends_on:
            if isinstance(dep, int):
                if 0 <= dep < len(steps):
                    dep_ids.append(steps[dep]["id"])
            else:
                dep_ids.append(str(dep))
        return dep_ids

    # ------------------------------------------------------------------
    # Public Status / Memory Access
    # ------------------------------------------------------------------

    def get_status(self, step_id: str) -> Optional[Dict[str, Any]]:
        """Get status dict for a specific step."""
        return self.status_manager.get(step_id)

    def get_memory(self) -> Dict[str, Any]:
        """Get a copy of the current workflow memory (all step outputs)."""
        return self.memory.copy()
