"""
Step Claimer - Matches workflow steps to capable agents

Simplified from integration-agent (260 lines → 80 lines)
Focused on capability matching without Kafka integration.
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class StepClaimer:
    """
    Matches workflow steps to agents based on capabilities.

    Simplified from integration-agent's version.
    Removes: Lazy evaluation, external dependency tracking, Kafka claims
    Keeps: Core capability matching logic
    """

    def __init__(self, agents: List):
        """
        Initialize step claimer with available agents.

        Args:
            agents: List of Agent instances available for claiming
        """
        self.agents = agents
        self._capability_index = self._build_capability_index()
        logger.info(f"Step claimer initialized with {len(agents)} agents")

    def _build_capability_index(self) -> Dict[str, List]:
        """Build index of capabilities to agents."""
        index = {}
        for agent in self.agents:
            # Index by role
            if agent.role not in index:
                index[agent.role] = []
            index[agent.role].append(agent)

            # Index by each capability
            for cap in agent.capabilities:
                if cap not in index:
                    index[cap] = []
                index[cap].append(agent)

        logger.debug(f"Built capability index with {len(index)} entries")
        return index

    def find_agent(self, step: Dict[str, Any]) -> Optional[Any]:
        """
        Find agent capable of executing this step.

        Args:
            step: Step specification containing:
                - agent: Role or capability required
                - role: Alternative key for agent role
                - capability: Alternative key for capability

        Returns:
            Agent instance that can handle the step, or None

        Example:
            step = {"agent": "scraper", "task": "Scrape website"}
            agent = claimer.find_agent(step)
        """
        # Try different keys for agent requirement
        required = (
            step.get("agent") or
            step.get("role") or
            step.get("capability")
        )

        if not required:
            logger.warning(f"Step has no agent/role/capability specified: {step}")
            return None

        # Look up in capability index
        agents = self._capability_index.get(required, [])

        if not agents:
            logger.warning(f"No agent found for requirement: {required}")
            return None

        # Return first matching agent
        agent = agents[0]
        logger.debug(f"Matched step to agent: {agent.agent_id}")
        return agent

    def find_all_agents(self, capability: str) -> List[Any]:
        """
        Find all agents with a specific capability.

        Args:
            capability: Required capability

        Returns:
            List of agents with the capability
        """
        return self._capability_index.get(capability, [])
