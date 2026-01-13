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
        # Wrap code to capture result (matching integration agent behavior)
        wrapped_code = self._wrap_code_for_sandbox(code, context)

        # Encode code to base64
        code_b64 = base64.b64encode(wrapped_code.encode('utf-8')).decode('utf-8')

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
            # Use /normal endpoint for API tasks
            endpoint_url = f"{self.sandbox_url}/normal"

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint_url,
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

                    logger.debug(f"Remote sandbox response: {sandbox_response}")

                    # Extract result using robust method (matching integration agent)
                    actual_result = self._extract_sandbox_result(sandbox_response)

                    # Convert to our format
                    if actual_result.get('success') is False:
                        # Error case
                        return {
                            'status': 'failure',
                            'error': actual_result.get('error', 'Unknown error'),
                            'error_type': 'RemoteSandboxError'
                        }
                    else:
                        # Success case
                        return {
                            'status': 'success',
                            'output': actual_result.get('result', actual_result.get('data', actual_result.get('output')))
                        }

        except asyncio.TimeoutError:
            logger.error(f"Remote sandbox timeout after {timeout}s")
            raise ExecutionTimeout(f"Remote execution exceeded {timeout} seconds")

        except aiohttp.ClientError as e:
            # Network/HTTP errors
            logger.warning(f"Remote sandbox connection error: {e}. Falling back to local execution.")
            return await self._execute_local(code, timeout, context)

        except Exception as e:
            # Only fallback for actual execution errors, not during cleanup
            if "object has no attribute" not in str(e):
                logger.warning(f"Remote sandbox failed: {e}. Falling back to local execution.")
                return await self._execute_local(code, timeout, context)
            else:
                # This is likely a cleanup issue, just log and don't fallback
                logger.debug(f"Ignoring cleanup error: {e}")
                raise

    def _wrap_code_for_sandbox(self, code: str, context: Optional[Dict] = None) -> str:
        """
        Wrap code to capture and print result as JSON (matches integration agent).

        The sandbox executes code and captures stdout. We need to:
        1. Execute the code
        2. Extract the 'result' variable
        3. Print it as JSON to stdout

        Args:
            code: Python code to wrap
            context: Optional context variables

        Returns:
            Wrapped code that prints result as JSON
        """
        # Add imports if needed
        imports = []
        if 'import json' not in code:
            imports.append('import json')
        if 'import sys' not in code:
            imports.append('import sys')

        imports_str = '\n'.join(imports) + '\n' if imports else ''

        # Wrap code to capture and print result
        wrapper = f'''{imports_str}{code}

# JarvisCore: Capture and print result
if __name__ == "__main__":
    try:
        # Check if result variable exists
        if 'result' in locals() or 'result' in globals():
            output = {{"success": True, "result": result}}
        else:
            output = {{"success": False, "error": "No 'result' variable found"}}

        # Print as JSON to stdout (sandbox captures this)
        print(json.dumps(output))
        sys.exit(0)
    except Exception as e:
        error_output = {{
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }}
        print(json.dumps(error_output))
        sys.exit(1)
'''
        return wrapper

    def _extract_sandbox_result(self, sandbox_response: Any) -> Dict[str, Any]:
        """
        Extract the actual function result from sandbox response.
        Matches integration agent's robust extraction logic.

        Args:
            sandbox_response: Raw response from sandbox service

        Returns:
            Extracted result dict
        """
        # Handle None response
        if sandbox_response is None:
            logger.warning("Sandbox returned None response")
            return {
                "success": False,
                "error": "Sandbox returned null response",
                "error_type": "null_response"
            }

        # Handle non-dict response
        if not isinstance(sandbox_response, dict):
            logger.warning(f"Sandbox returned non-dict response: {type(sandbox_response)}")
            return {
                "success": False,
                "error": f"Sandbox returned unexpected response type: {type(sandbox_response)}",
                "error_type": "invalid_response_type"
            }

        # Try to parse 'output' field if it's a JSON string
        if 'output' in sandbox_response and isinstance(sandbox_response.get('output'), str):
            output_str = sandbox_response['output'].strip()
            if output_str:
                try:
                    parsed_output = json.loads(output_str)
                    if isinstance(parsed_output, dict):
                        logger.debug("Successfully parsed result from output field")
                        return parsed_output
                except json.JSONDecodeError as e:
                    logger.debug(f"JSON parse failed: {e}, trying line-by-line")
                    lines = output_str.strip().split('\n')
                    for line in reversed(lines):
                        line = line.strip()
                        if line.startswith('{') and line.endswith('}'):
                            try:
                                parsed_output = json.loads(line)
                                if isinstance(parsed_output, dict) and 'success' in parsed_output:
                                    logger.debug("Successfully parsed result from last JSON line")
                                    return parsed_output
                            except json.JSONDecodeError:
                                continue

                    logger.warning("Could not parse any JSON from output")
                    return {
                        "success": sandbox_response.get('success', False),
                        "output": output_str,
                        "error": sandbox_response.get('error') or "Failed to parse output as JSON"
                    }

        # If response has 'success' field but no nested result fields, return as-is
        if 'success' in sandbox_response:
            wrapper_fields = {'result', 'function_result', 'execution_result'}
            if not any(field in sandbox_response for field in wrapper_fields):
                return sandbox_response

        # Try common result field names
        result_candidates = ['result', 'function_result', 'execution_result', 'data', 'response']
        for field in result_candidates:
            if field in sandbox_response and sandbox_response[field] is not None:
                candidate = sandbox_response[field]
                if isinstance(candidate, dict):
                    return candidate

        logger.debug(f"No specific result field found, returning whole response")
        return sandbox_response

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
