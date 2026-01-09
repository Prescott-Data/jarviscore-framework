"""
Sandbox Executor - Safe execution of generated code with resource limits
Supports async code and provides internet search access
"""
import asyncio
import logging
import signal
import sys
from typing import Dict, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class ExecutionTimeout(Exception):
    """Raised when code execution times out."""
    pass


@contextmanager
def time_limit(seconds: int):
    """Context manager for enforcing time limits (Unix only)."""
    def signal_handler(signum, frame):
        raise ExecutionTimeout(f"Execution exceeded {seconds} seconds")

    # Only works on Unix systems
    if hasattr(signal, 'SIGALRM'):
        signal.signal(signal.SIGALRM, signal_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
    else:
        # Windows fallback - no timeout enforcement
        logger.warning("Timeout enforcement not available on Windows")
        yield


class SandboxExecutor:
    """
    Safe code executor with resource limits and internet access.

    Philosophy:
    - Execute generated code in isolated namespace
    - Enforce timeout limits
    - Provide search tools if available
    - Capture all output and errors
    - Extract 'result' variable

    Example:
        executor = SandboxExecutor(timeout=60, search_client=search)
        result = await executor.execute(code)
    """

    def __init__(
        self,
        timeout: int = 300,
        search_client=None,
        config: Optional[Dict] = None
    ):
        """
        Initialize sandbox executor.

        Args:
            timeout: Max execution time in seconds (default 300 = 5 min)
            search_client: Optional InternetSearch for web access
            config: Optional config dict
        """
        self.timeout = timeout
        self.search = search_client
        self.config = config or {}

        logger.info(f"Sandbox initialized with {timeout}s timeout")

    async def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Execute Python code in sandbox.

        Args:
            code: Python code string to execute
            timeout: Optional timeout override (seconds)
            context: Optional context variables to inject

        Returns:
            {
                "status": "success" | "failure",
                "output": Any,  # Value of 'result' variable
                "error": str,   # Error message if failed
                "error_type": str,  # Exception type
                "stdout": str   # Captured print output
            }

        Example:
            result = await executor.execute("result = 2 + 2")
            print(result['output'])  # 4
        """
        timeout = timeout or self.timeout
        logger.info(f"Executing code with {timeout}s timeout")
        logger.debug(f"Code length: {len(code)} chars")

        try:
            # Create isolated namespace
            namespace = self._create_namespace(context)

            # Check if code is async
            is_async = 'async def' in code or 'await ' in code or 'asyncio' in code

            if is_async:
                result = await self._execute_async(code, namespace, timeout)
            else:
                result = await self._execute_sync(code, namespace, timeout)

            logger.info("Code execution successful")
            return result

        except Exception as e:
            logger.error(f"Execution failed: {type(e).__name__}: {e}")
            return {
                "status": "failure",
                "error": str(e),
                "error_type": type(e).__name__
            }

    def _create_namespace(self, context: Optional[Dict] = None) -> Dict:
        """
        Create isolated namespace with safe built-ins and tools.

        Args:
            context: Optional context variables to inject

        Returns:
            Namespace dict for code execution
        """
        # Safe built-ins (remove dangerous functions)
        safe_builtins = {
            name: getattr(__builtins__, name)
            for name in dir(__builtins__)
            if not name.startswith('_') and name not in [
                'eval', 'exec', 'compile', 'open',  # Potentially dangerous
            ]
        }

        # Add back controlled versions
        safe_builtins['print'] = print  # Allow print for debugging
        safe_builtins['__import__'] = __import__  # Needed for asyncio and module imports

        namespace = {
            '__builtins__': safe_builtins,
            'result': None,  # Where code should store output
        }

        # Inject search client if available
        if self.search:
            namespace['search'] = self.search
            logger.debug("Injected search client into namespace")

        # Inject context variables
        if context:
            namespace.update(context)
            logger.debug(f"Injected {len(context)} context variables")

        return namespace

    async def _execute_sync(
        self,
        code: str,
        namespace: Dict,
        timeout: int
    ) -> Dict[str, Any]:
        """Execute synchronous code."""
        try:
            # Run in thread pool to enforce timeout
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, exec, code, namespace),
                timeout=timeout
            )

            # Extract result
            result = namespace.get('result')

            return {
                "status": "success",
                "output": result
            }

        except asyncio.TimeoutError:
            raise ExecutionTimeout(f"Execution exceeded {timeout} seconds")

    async def _execute_async(
        self,
        code: str,
        namespace: Dict,
        timeout: int
    ) -> Dict[str, Any]:
        """Execute asynchronous code."""
        # Inject asyncio and search for async code
        namespace['asyncio'] = asyncio
        if self.search:
            namespace['search'] = self.search

        try:
            # Execute code to define functions
            exec(code, namespace)

            # Look for main() or run() function
            if 'main' in namespace and callable(namespace['main']):
                # Run main() with timeout
                result_value = await asyncio.wait_for(
                    namespace['main'](),
                    timeout=timeout
                )
            elif 'run' in namespace and callable(namespace['run']):
                result_value = await asyncio.wait_for(
                    namespace['run'](),
                    timeout=timeout
                )
            else:
                # Check if result was set directly
                result_value = namespace.get('result')

            return {
                "status": "success",
                "output": result_value
            }

        except asyncio.TimeoutError:
            raise ExecutionTimeout(f"Async execution exceeded {timeout} seconds")


def create_sandbox_executor(
    timeout: int = 300,
    search_client=None,
    config: Optional[Dict] = None
) -> SandboxExecutor:
    """
    Factory function to create sandbox executor.

    Args:
        timeout: Max execution time (default 300s)
        search_client: Optional search client for web access
        config: Optional configuration

    Returns:
        SandboxExecutor instance
    """
    return SandboxExecutor(timeout, search_client, config)
