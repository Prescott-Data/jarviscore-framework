"""
6F: CoderSubAgent — Code generation and execution specialist.

The coder generates Python code to fulfill tasks, validates it with
ast.parse before execution, runs it in the sandbox, and handles
repair on failure (up to a configurable retry limit).

Design decisions (from IA/CA analysis):
- Adopted: Pre-execution syntax validation (CA pattern — catches errors before sandbox)
- Adopted: Candidate artifact versioning (CA — track each attempt for audit)
- Adopted: Auth error classification (IA — expired_token, missing_auth, etc.)
- Avoided: Silent repair failures (CA bug — we surface all errors in trajectory)
- Avoided: Fragile regex code extraction (both — we use text-based protocol)
"""

import ast
import logging
from typing import Any, Dict, List, Optional

from jarviscore.kernel.subagent import BaseSubAgent

logger = logging.getLogger(__name__)

# Auth error patterns for classification
_AUTH_ERROR_PATTERNS = {
    "expired_token": ["token expired", "token has expired", "jwt expired"],
    "missing_auth": ["authentication required", "no auth", "missing token", "unauthorized"],
    "invalid_token": ["invalid token", "bad token", "malformed token"],
    "permission_denied": ["forbidden", "permission denied", "insufficient scope", "access denied"],
}


def classify_auth_error(error_msg: str) -> Optional[str]:
    """Classify an error message into an auth error category, or None."""
    lower = error_msg.lower()
    for category, patterns in _AUTH_ERROR_PATTERNS.items():
        if any(p in lower for p in patterns):
            return category
    return None


class CoderSubAgent(BaseSubAgent):
    """
    Code generation subagent for the kernel.

    Tools:
    - write_code: Generate Python code (thinking phase)
    - validate_code: Syntax-check with ast.parse (thinking phase)
    - execute_code: Run in sandbox (action phase)

    The coder is write-and-execute: it generates code, validates syntax,
    runs it in the sandbox, and can repair on failure. Each attempt is
    versioned in the trajectory for audit.
    """

    def __init__(
        self,
        agent_id: str,
        llm_client,
        sandbox=None,
        code_registry=None,
        redis_store=None,
        blob_storage=None,
        max_repair_attempts: int = 2,
    ):
        self.sandbox = sandbox
        self.code_registry = code_registry
        self.max_repair_attempts = max_repair_attempts
        self._candidates: List[Dict[str, Any]] = []
        super().__init__(
            agent_id=agent_id,
            role="coder",
            llm_client=llm_client,
            redis_store=redis_store,
            blob_storage=blob_storage,
        )

    def get_system_prompt(self) -> str:
        return (
            "You are a code generation specialist. You write clean, correct Python code "
            "to accomplish tasks. Follow this workflow:\n"
            "1. Use write_code to generate your solution\n"
            "2. Use validate_code to check syntax before execution\n"
            "3. Use execute_code to run in the sandbox\n"
            "4. If execution fails, analyze the error and repair (up to "
            f"{self.max_repair_attempts} attempts)\n\n"
            "Rules:\n"
            "- Always validate before executing\n"
            "- Store your final result in a variable called 'result'\n"
            "- Handle errors explicitly — do not silently swallow them\n"
            "- If you detect an auth error, report it clearly in your DONE summary"
        )

    def setup_tools(self) -> None:
        self.register_tool(
            "write_code",
            self._tool_write_code,
            "Generate Python code. Params: {\"code\": \"<python code>\"}",
            phase="thinking",
        )
        self.register_tool(
            "validate_code",
            self._tool_validate_code,
            "Validate Python syntax with ast.parse. Params: {\"code\": \"<python code>\"}",
            phase="thinking",
        )
        self.register_tool(
            "execute_code",
            self._tool_execute_code,
            "Execute code in the sandbox. Params: {\"code\": \"<python code>\"}",
            phase="action",
        )

    def _tool_write_code(self, code: str) -> Dict[str, Any]:
        """Record a code candidate (versioned)."""
        version = len(self._candidates) + 1
        candidate = {
            "version": version,
            "code": code,
            "status": "drafted",
        }
        self._candidates.append(candidate)
        return {"version": version, "status": "drafted", "length": len(code)}

    def _tool_validate_code(self, code: str) -> Dict[str, Any]:
        """Validate Python syntax using ast.parse."""
        try:
            ast.parse(code)
            return {"valid": True}
        except SyntaxError as e:
            return {
                "valid": False,
                "error": str(e),
                "line": e.lineno,
                "offset": e.offset,
            }

    async def _tool_execute_code(self, code: str) -> Dict[str, Any]:
        """Execute code in the sandbox."""
        if not self.sandbox:
            return {"status": "error", "error": "No sandbox configured"}

        # Inject system bundle if code_registry detects dependencies
        exec_code = code
        if self.code_registry:
            try:
                systems = self.code_registry.detect_system_dependencies(code)
                if systems:
                    exec_code = self.code_registry.prepare_code_with_bundle(
                        code, systems[0]
                    )
            except Exception as e:
                logger.warning(f"Bundle injection failed: {e}")

        result = await self.sandbox.execute(exec_code)

        # Classify auth errors if execution failed
        if result.get("status") == "failure" and result.get("error"):
            auth_category = classify_auth_error(result["error"])
            if auth_category:
                result["auth_error_type"] = auth_category

        # Update candidate status
        for candidate in reversed(self._candidates):
            if candidate["code"] == code:
                candidate["status"] = result.get("status", "unknown")
                break

        return result

    @property
    def candidates(self) -> List[Dict[str, Any]]:
        """All code candidates generated during this run."""
        return list(self._candidates)

    async def run(self, task, context=None, max_turns=5, model=None):
        """Run with fresh candidate list."""
        self._candidates = []
        return await super().run(task, context, max_turns, model)
