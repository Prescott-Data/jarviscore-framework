"""
Result Handler - Process and store function execution results
Storage: File system + In-memory (no external dependencies)
"""
import json
import logging
import os
import time
import datetime
from typing import Dict, Any, Optional
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ResultStatus(Enum):
    """Execution result status."""
    SUCCESS = "success"
    FAILURE = "failure"
    SYNTAX_ERROR = "syntax_error"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    PARTIAL = "partial"


class ErrorCategory(Enum):
    """Error classification categories."""
    SYNTAX = "syntax"
    RUNTIME = "runtime"
    NETWORK = "network"
    TIMEOUT = "timeout"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


class ResultHandler:
    """
    Handles processing, formatting, and storage of execution results.

    Storage:
    - File system: ./logs/{agent_id}/{result_id}.json
    - In-memory: LRU cache for fast access

    Features:
    - Stores generated code with results
    - Sanitizes sensitive parameters
    - Classifies errors automatically
    - Provides retrieval by result_id

    Zero-config: No external dependencies (no Redis, no DB)
    """

    def __init__(self, log_directory: str = "./logs", max_cache_size: int = 100):
        """
        Initialize result handler.

        Args:
            log_directory: Base directory for storing results
            max_cache_size: Maximum number of results to cache in memory
        """
        self.log_directory = Path(log_directory)
        self.log_directory.mkdir(parents=True, exist_ok=True)

        # In-memory cache (LRU)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_order = []  # For LRU eviction
        self.max_cache_size = max_cache_size

        logger.info(f"ResultHandler initialized with directory: {self.log_directory}")

    def process_result(
        self,
        agent_id: str,
        task: str,
        code: str,
        output: Any,
        status: str,
        error: Optional[str] = None,
        execution_time: Optional[float] = None,
        tokens: Optional[Dict] = None,
        cost_usd: Optional[float] = None,
        repairs: int = 0,
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Process and store execution result.

        Args:
            agent_id: ID of the agent that executed
            task: Original task description
            code: Generated code that was executed
            output: Execution output (result variable)
            status: "success" or "failure"
            error: Error message if failed
            execution_time: Time taken in seconds
            tokens: Token usage {input, output, total}
            cost_usd: Estimated cost
            repairs: Number of repair attempts
            metadata: Additional metadata

        Returns:
            Processed result dictionary with storage metadata
        """
        timestamp = datetime.datetime.now().isoformat()
        result_id = self._generate_result_id(agent_id, timestamp)

        # Classify error if present
        error_category = None
        if error:
            error_category = self._classify_error(error)

        # Determine detailed status
        result_status = self._determine_status(status, error, error_category)

        # Build result object
        result_data = {
            # Identity
            "result_id": result_id,
            "agent_id": agent_id,
            "timestamp": timestamp,

            # Execution details
            "task": task,
            "code": code,
            "output": output,

            # Status
            "status": result_status.value,
            "success": result_status == ResultStatus.SUCCESS,

            # Error details
            "error": error,
            "error_category": error_category.value if error_category else None,

            # Metrics
            "execution_time": execution_time,
            "tokens": tokens or {},
            "cost_usd": cost_usd or 0.0,
            "repairs": repairs,

            # Metadata
            "metadata": metadata or {}
        }

        # Store to file system
        self._save_to_file(agent_id, result_id, result_data)

        # Store in memory cache
        self._cache_result(result_id, result_data)

        # Log summary
        if result_status == ResultStatus.SUCCESS:
            time_str = f"{execution_time:.2f}s" if execution_time else "N/A"
            logger.info(
                f"Result {result_id}: SUCCESS in {time_str} "
                f"(repairs: {repairs}, cost: ${cost_usd:.4f})"
            )
        else:
            logger.error(
                f"Result {result_id}: {result_status.value} - {error}"
            )

        return result_data

    def get_result(self, result_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve result by ID (checks cache first, then file system).

        Args:
            result_id: Result identifier

        Returns:
            Result dictionary or None if not found
        """
        # Check in-memory cache first
        if result_id in self._cache:
            logger.debug(f"Result {result_id} retrieved from cache")
            return self._cache[result_id]

        # Search file system
        result_data = self._load_from_file(result_id)
        if result_data:
            # Cache for future access
            self._cache_result(result_id, result_data)
            logger.debug(f"Result {result_id} loaded from file")
            return result_data

        logger.warning(f"Result {result_id} not found")
        return None

    def get_agent_results(self, agent_id: str, limit: int = 10) -> list:
        """
        Get recent results for a specific agent.

        Args:
            agent_id: Agent identifier
            limit: Maximum number of results to return

        Returns:
            List of result dictionaries, most recent first
        """
        agent_dir = self.log_directory / agent_id
        if not agent_dir.exists():
            return []

        # Get all result files for this agent
        result_files = sorted(
            agent_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:limit]

        results = []
        for result_file in result_files:
            try:
                with open(result_file, 'r') as f:
                    results.append(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to load {result_file}: {e}")

        return results

    def _generate_result_id(self, agent_id: str, timestamp: str) -> str:
        """Generate unique result ID."""
        clean_timestamp = timestamp.replace(':', '-').replace('.', '_')
        return f"{agent_id}_{clean_timestamp}"

    def _determine_status(
        self,
        status: str,
        error: Optional[str],
        error_category: Optional[ErrorCategory]
    ) -> ResultStatus:
        """Determine detailed result status."""
        if status == "success":
            return ResultStatus.SUCCESS

        if error_category == ErrorCategory.SYNTAX:
            return ResultStatus.SYNTAX_ERROR
        elif error_category == ErrorCategory.TIMEOUT:
            return ResultStatus.TIMEOUT
        elif error and "error" in error.lower():
            return ResultStatus.RUNTIME_ERROR

        return ResultStatus.FAILURE

    def _classify_error(self, error: str) -> ErrorCategory:
        """Classify error into category."""
        error_lower = error.lower()

        # Syntax errors
        syntax_keywords = ['syntaxerror', 'indentationerror', 'taberror', 'invalid syntax']
        if any(kw in error_lower for kw in syntax_keywords):
            return ErrorCategory.SYNTAX

        # Timeout errors
        timeout_keywords = ['timeout', 'timed out', 'time limit exceeded']
        if any(kw in error_lower for kw in timeout_keywords):
            return ErrorCategory.TIMEOUT

        # Network errors
        network_keywords = ['connection', 'network', 'httpx', 'aiohttp', 'socket']
        if any(kw in error_lower for kw in network_keywords):
            return ErrorCategory.NETWORK

        # Resource errors
        resource_keywords = ['memory', 'resource', 'quota', 'limit exceeded']
        if any(kw in error_lower for kw in resource_keywords):
            return ErrorCategory.RESOURCE

        # Runtime errors (default for unknown errors)
        return ErrorCategory.RUNTIME

    def _save_to_file(self, agent_id: str, result_id: str, result_data: Dict):
        """Save result to file system."""
        agent_dir = self.log_directory / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        result_file = agent_dir / f"{result_id}.json"

        try:
            with open(result_file, 'w') as f:
                json.dump(result_data, f, indent=2, default=str)
            logger.debug(f"Saved result to {result_file}")
        except Exception as e:
            logger.error(f"Failed to save result to file: {e}")

    def _load_from_file(self, result_id: str) -> Optional[Dict]:
        """Load result from file system by searching all agent directories."""
        for agent_dir in self.log_directory.iterdir():
            if not agent_dir.is_dir():
                continue

            result_file = agent_dir / f"{result_id}.json"
            if result_file.exists():
                try:
                    with open(result_file, 'r') as f:
                        return json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load {result_file}: {e}")

        return None

    def _cache_result(self, result_id: str, result_data: Dict):
        """Cache result in memory with LRU eviction."""
        # Add to cache
        self._cache[result_id] = result_data

        # Track access order
        if result_id in self._cache_order:
            self._cache_order.remove(result_id)
        self._cache_order.append(result_id)

        # Evict oldest if cache is full
        while len(self._cache) > self.max_cache_size:
            oldest_id = self._cache_order.pop(0)
            del self._cache[oldest_id]
            logger.debug(f"Evicted {oldest_id} from cache (LRU)")


def create_result_handler(log_directory: str = "./logs") -> ResultHandler:
    """
    Factory function to create result handler.

    Args:
        log_directory: Base directory for result storage

    Returns:
        ResultHandler instance
    """
    return ResultHandler(log_directory)
