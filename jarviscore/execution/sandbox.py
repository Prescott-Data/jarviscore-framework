"""
Sandbox Executor - Safe execution of generated code with resource limits
Supports async code and provides internet search access

Modes:
- local: In-process execution (development/testing)
- remote: HTTP POST to sandbox service (production)
"""
import asyncio
import aiohttp
import base64
import json
import logging
import signal
import sys
import time
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

    Modes:
    - local: In-process exec() (fast, for development)
    - remote: HTTP POST to sandbox service (isolated, for production)

    Philosophy:
    - Execute generated code in isolated namespace
    - Enforce timeout limits
    - Provide search tools if available
    - Capture all output and errors
    - Extract 'result' variable

    Example:
        # Local mode (development)
        executor = SandboxExecutor(mode="local")

        # Remote mode (production)
        executor = SandboxExecutor(
            mode="remote",
            sandbox_url="https://sandbox.mycompany.com/execute"
        )
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
            config: Optional config dict with:
                - sandbox_mode: "local" or "remote"
                - sandbox_service_url: URL for remote sandbox
        """
        self.timeout = timeout
        self.search = search_client
        self.config = config or {}

        # Determine execution mode
        self.mode = self.config.get('sandbox_mode', 'local').lower()
        self.sandbox_url = self.config.get('sandbox_service_url')

        if self.mode == 'remote' and not self.sandbox_url:
            logger.warning(
                "Remote sandbox mode requires sandbox_service_url. "
                "Falling back to local mode."
            )
            self.mode = 'local'

        logger.info(f"Sandbox initialized: mode={self.mode}, timeout={timeout}s")

    async def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Execute Python code in sandbox (local or remote).

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
                "execution_time": float,  # Seconds taken
                "mode": "local" | "remote"  # Execution mode used
            }

        Example:
            result = await executor.execute("result = 2 + 2")
            print(result['output'])  # 4
        """
        timeout = timeout or self.timeout
        start_time = time.time()

        logger.info(f"Executing code ({self.mode} mode, {timeout}s timeout)")
        logger.debug(f"Code length: {len(code)} chars")

        try:
            # Route to appropriate execution method
            if self.mode == 'remote':
                result = await self._execute_remote(code, timeout, context)
            else:
                result = await self._execute_local(code, timeout, context)

            # Add execution metadata
            execution_time = time.time() - start_time
            result['execution_time'] = execution_time
            result['mode'] = self.mode

            logger.info(f"Code execution successful ({execution_time:.3f}s)")
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Execution failed: {type(e).__name__}: {e}")
            return {
                "status": "failure",
                "error": str(e),
                "error_type": type(e).__name__,
                "execution_time": execution_time,
                "mode": self.mode
            }

    async def _execute_local(
        self,
        code: str,
        timeout: int,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Execute code locally in-process."""
        # Create isolated namespace
        namespace = self._create_namespace(context)

        # Check if code is async
        is_async = 'async def' in code or 'await ' in code or 'asyncio' in code

        if is_async:
            return await self._execute_async(code, namespace, timeout)
        else:
            return await self._execute_sync(code, namespace, timeout)

    async def _execute_remote(
        self,
        code: str,
        timeout: int,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Execute code via remote sandbox service (Azure Container Apps).

        Matches integration-agent format:
        {
            "STEP_DATA": {
                "id": "job_id",
                "function_name": "generated_code",
                "parameters": {},
                "options": {}
            },
            "TASK_CODE_B64": "base64_encoded_code"
        }

        Expects response:
        {
            "success": true/false,
            "result": ...,
            "error": "...",
            ...
        }
        """
        # Encode code to base64
        code_b64 = base64.b64encode(code.encode('utf-8')).decode('utf-8')

        # Prepare payload in Azure Container Apps format
        payload = {
            "STEP_DATA": {
                "id": f"jarviscore_{int(time.time())}",
                "function_name": "generated_code",
                "parameters": context or {},
                "options": {"timeout": timeout}
            },
            "TASK_CODE_B64": code_b64
        }

        try:
            # Make HTTP request to sandbox service
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.sandbox_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=timeout + 10)  # Buffer
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(
                            f"Sandbox service error ({response.status}): {error_text}"
                        )

                    sandbox_response = await response.json()
                    logger.debug(f"Remote sandbox response: {sandbox_response.get('success')}")

                    # Extract result from Azure Container Apps response format
                    if sandbox_response.get('success'):
                        # Success - extract the result
                        output = sandbox_response.get('result')
                        return {
                            'status': 'success',
                            'output': output
                        }
                    else:
                        # Error - extract error message
                        error_msg = sandbox_response.get('error', 'Unknown error')
                        return {
                            'status': 'failure',
                            'error': error_msg,
                            'error_type': 'RemoteSandboxError'
                        }

        except asyncio.TimeoutError:
            logger.error(f"Remote sandbox timeout after {timeout}s")
            raise ExecutionTimeout(f"Remote execution exceeded {timeout} seconds")

        except Exception as e:
            # If remote execution fails, fallback to local
            logger.warning(f"Remote sandbox failed: {e}. Falling back to local execution.")
            return await self._execute_local(code, timeout, context)

    def _create_namespace(self, context: Optional[Dict] = None) -> Dict:
        """
        Create isolated namespace with safe built-ins and tools.

        Args:
            context: Optional context variables to inject

        Returns:
            Namespace dict for code execution
        """
        # Get all built-ins except dangerous ones
        safe_builtins = {}
        for name in dir(__builtins__):
            if name.startswith('_'):
                continue
            # Exclude dangerous functions
            if name in ['eval', 'exec', 'compile', 'open', 'input', 'file']:
                continue
            try:
                safe_builtins[name] = getattr(__builtins__, name)
            except AttributeError:
                pass

        # Ensure critical built-ins are present
        critical_builtins = [
            'print', '__import__', 'len', 'range', 'str', 'int', 'float',
            'list', 'dict', 'set', 'tuple', 'bool', 'type', 'isinstance',
            'min', 'max', 'sum', 'sorted', 'enumerate', 'zip', 'map', 'filter',
            'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
            'NameError', 'AttributeError', 'RuntimeError', 'ZeroDivisionError'
        ]

        for builtin in critical_builtins:
            if builtin not in safe_builtins:
                try:
                    safe_builtins[builtin] = eval(builtin)
                except:
                    logger.warning(f"Could not add built-in: {builtin}")

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
