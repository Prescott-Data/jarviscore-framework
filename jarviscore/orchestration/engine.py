"""
Workflow Engine - Orchestrates multi-step workflow execution

Core orchestration logic adapted from integration-agent.
Simplified for jarviscore MVP.
"""
import logging
import asyncio
from typing import List, Dict, Any, Optional

from .claimer import StepClaimer
from .dependency import DependencyManager
from .status import StatusManager

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Executes multi-step workflows with dependency management.

    Simplified from integration-agent's workflow_processor.py (2600 lines → 200 lines)
    Removes: Kafka integration, repair system, LLM nudging
    Keeps: Core execution loop, dependency resolution, status tracking
    """

    def __init__(
        self,
        mesh,
        p2p_coordinator=None,
        config: Optional[Dict] = None
    ):
        """
        Initialize workflow engine.

        Args:
            mesh: Mesh instance containing agents
            p2p_coordinator: Optional P2P coordinator for distributed execution
            config: Optional configuration dictionary
        """
        self.mesh = mesh
        self.p2p = p2p_coordinator
        self.config = config or {}

        # Core components
        self.claimer = StepClaimer(mesh.agents)
        self.status_manager = StatusManager()

        # Working memory (step_id -> result)
        self.memory: Dict[str, Any] = {}
        self.dependency_manager = DependencyManager(self.memory)

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
        """Stop the workflow engine."""
        if not self._started:
            return

        self._started = False
        self.memory.clear()
        self.status_manager.clear()
        logger.info("Workflow engine stopped")

    async def execute(
        self,
        workflow_id: str,
        steps: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute a multi-step workflow.

        Args:
            workflow_id: Unique workflow identifier
            steps: List of step specifications:
                [
                    {
                        "id": "step1",  # Optional, auto-generated if missing
                        "agent": "role_or_capability",
                        "task": "Task description",
                        "depends_on": []  # Optional list of step IDs
                    }
                ]

        Returns:
            List of result dictionaries (one per step)

        Example:
            results = await engine.execute("pipeline-1", [
                {"agent": "scraper", "task": "Scrape data"},
                {"agent": "processor", "task": "Process data", "depends_on": [0]},
                {"agent": "storage", "task": "Save data", "depends_on": [1]}
            ])
        """
        if not self._started:
            raise RuntimeError("Workflow engine not started. Call start() first.")

        logger.info(
            f"Executing workflow {workflow_id} with {len(steps)} step(s)"
        )

        # Normalize steps (ensure each has an ID)
        normalized_steps = self._normalize_steps(steps)

        results = []

        for i, step in enumerate(normalized_steps):
            step_id = step.get('id', f'step{i}')
            logger.info(f"Processing step {i+1}/{len(steps)}: {step_id}")

            try:
                # 1. Update status to pending
                self.status_manager.update(step_id, 'pending')

                # 2. Claim step (find capable agent)
                agent = self.claimer.find_agent(step)
                if not agent:
                    error_msg = f"No agent found for step: {step}"
                    logger.error(error_msg)
                    self.status_manager.update(step_id, 'failed', error=error_msg)
                    results.append({
                        'status': 'failure',
                        'error': error_msg,
                        'step': i
                    })
                    continue

                logger.info(f"Step {step_id} claimed by: {agent.agent_id}")

                # 3. Resolve dependencies
                if depends_on := step.get('depends_on'):
                    logger.info(f"Step {step_id} has {len(depends_on)} dependencies")

                    # Convert numeric indices to step IDs
                    dep_ids = self._resolve_dependency_ids(depends_on, normalized_steps)

                    try:
                        await self.dependency_manager.wait_for(
                            dep_ids,
                            self.memory,
                            timeout=self.config.get('execution_timeout', 300)
                        )
                        logger.info(f"Dependencies satisfied for step {step_id}")
                    except TimeoutError as e:
                        error_msg = f"Dependency timeout: {e}"
                        logger.error(error_msg)
                        self.status_manager.update(step_id, 'failed', error=error_msg)
                        results.append({
                            'status': 'failure',
                            'error': error_msg,
                            'step': i
                        })
                        continue

                # 4. Update status to in_progress
                self.status_manager.update(step_id, 'in_progress')

                # 5. Prepare task with context from dependencies
                task = step.copy()

                # Inject dependency outputs as context
                if depends_on := step.get('depends_on'):
                    dep_ids = self._resolve_dependency_ids(depends_on, normalized_steps)
                    dep_outputs = {}
                    for dep_id in dep_ids:
                        if dep_id in self.memory:
                            dep_result = self.memory[dep_id]
                            # Extract output from result
                            output = dep_result.get('output') if isinstance(dep_result, dict) else dep_result
                            dep_outputs[dep_id] = output

                    # Add dependency outputs to task context
                    task['context'] = {
                        'previous_step_results': dep_outputs,
                        'workflow_id': workflow_id,
                        'step_id': step_id
                    }
                    logger.debug(f"Injected context with {len(dep_outputs)} dependencies")

                # 6. Execute step with context
                logger.info(f"Executing step {step_id} with agent {agent.agent_id}")
                result = await agent.execute_task(task)

                # Ensure result includes agent_id
                if isinstance(result, dict) and 'agent' not in result:
                    result['agent'] = agent.agent_id

                # 6. Store result in memory
                self.memory[step_id] = result
                logger.debug(f"Stored result for step {step_id} in memory")

                # 7. Broadcast result to P2P mesh (if available)
                if self.p2p and hasattr(self.p2p, 'broadcaster'):
                    try:
                        await self.p2p.broadcaster.broadcast_step_result(
                            step_id=step_id,
                            workflow_id=workflow_id,
                            output_data=result,
                            status='success'
                        )
                        logger.debug(f"Broadcasted result for step {step_id}")
                    except Exception as broadcast_error:
                        # Don't fail the step if broadcast fails
                        logger.warning(
                            f"Failed to broadcast step {step_id}: {broadcast_error}"
                        )

                # 8. Update status to completed
                self.status_manager.update(step_id, 'completed', output=result)

                # 9. Add to results
                results.append(result)
                logger.info(f"Step {step_id} completed successfully")

            except Exception as e:
                logger.error(f"Step {step_id} failed: {e}", exc_info=True)
                self.status_manager.update(step_id, 'failed', error=str(e))
                results.append({
                    'status': 'failure',
                    'error': str(e),
                    'step': i
                })
                # Don't stop workflow on single step failure
                # Continue to next step

        logger.info(
            f"Workflow {workflow_id} completed: "
            f"{len(results)}/{len(steps)} steps finished"
        )
        return results

    def _normalize_steps(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize step specifications (ensure each has an ID).

        Args:
            steps: Raw step list

        Returns:
            Normalized step list with IDs
        """
        normalized = []
        for i, step in enumerate(steps):
            if 'id' not in step:
                step = step.copy()
                step['id'] = f'step{i}'
            normalized.append(step)
        return normalized

    def _resolve_dependency_ids(
        self,
        depends_on: List,
        steps: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Convert dependency references to step IDs.

        Args:
            depends_on: List of step indices or IDs
            steps: All workflow steps

        Returns:
            List of step IDs
        """
        dep_ids = []
        for dep in depends_on:
            if isinstance(dep, int):
                # Index reference
                if 0 <= dep < len(steps):
                    dep_ids.append(steps[dep]['id'])
            else:
                # Direct ID reference
                dep_ids.append(str(dep))
        return dep_ids

    def get_status(self, step_id: str) -> Optional[Dict[str, Any]]:
        """Get status for a specific step."""
        return self.status_manager.get(step_id)

    def get_memory(self) -> Dict[str, Any]:
        """Get current workflow memory (all step outputs)."""
        return self.memory.copy()
