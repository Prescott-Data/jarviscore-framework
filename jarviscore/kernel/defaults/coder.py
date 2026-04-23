"""
CoderSubAgent — Production-grade code generation and execution specialist.

Doctrine:
  1. CODE FROM KNOWLEDGE FIRST — write code from training data, don't research first
  2. FALLBACK LADDER — write_code → quick search on concrete unknown → delegate_research
  3. SAFETY FIRST — try/except everywhere, never fail silently
  4. DIAGNOSE BEFORE RETRY — form a hypothesis about WHY before next attempt
  5. VERIFY BEFORE DONE — must have evidence the function works (execution output)
  6. REPORT FAITHFULLY — if code failed, say so in the summary
  7. NO SCOPE CREEP — do exactly what was asked, nothing more
  8. RESPECT AUTH — never hardcode tokens; use auth dict from namespace
  9. REGISTER SUCCESS — promote working code to FunctionRegistry
  10. ASK FOR HELP — delegate_research when stuck, not when lazy
"""

import ast
import logging
import time
from typing import Any, Dict, List, Optional

from jarviscore.kernel.subagent import BaseSubAgent
from jarviscore.kernel.state import KernelState

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Auth Error Classification
# ─────────────────────────────────────────────────────────────────

_AUTH_ERROR_PATTERNS = {
    "expired_token": [
        "token expired", "token has expired", "jwt expired",
        "access token expired", "refresh token expired",
    ],
    "missing_auth": [
        "authentication required", "no auth", "missing token",
        "unauthorized", "401",
    ],
    "invalid_token": [
        "invalid token", "bad token", "malformed token",
        "invalid credentials", "invalid access token",
    ],
    "permission_denied": [
        "forbidden", "permission denied", "insufficient scope",
        "access denied", "403", "not authorized",
    ],
}


def classify_auth_error(error_msg: str) -> Optional[str]:
    """Classify error message into auth category, or None if not auth-related."""
    lower = error_msg.lower()
    for category, patterns in _AUTH_ERROR_PATTERNS.items():
        if any(p in lower for p in patterns):
            return category
    return None


# ─────────────────────────────────────────────────────────────────
# CoderSubAgent
# ─────────────────────────────────────────────────────────────────

class CoderSubAgent(BaseSubAgent):
    """
    Code generation + execution subagent.

    Execution order:
    1. check_registry(task)        → if reuse found, skip to execute
    2. write_code(task)            → ValidationLayer → CandidateStore
    3. execute_code(function_name) → SandboxExecutor
    4. On success → register in FunctionRegistry (VERIFIED stage)
    5. On failure → diagnose error, fix code, re-execute (max 2 attempts)
    6. On persistent failure → delegate_research (HARD GATE: must write first)
    """

    DEFAULT_SYSTEM_PROMPT = """\
You are a CODE EXECUTION SPECIALIST in a multi-agent orchestration framework.
Your ONE job: write Python code that WORKS, execute it, and return real results.

## CRITICAL RULES (read all before acting)

1. **CODE, DON'T META-CODE** — Produce actual Python functions, not plans or descriptions.
   Wrong: "I would write a function that calls the API..."
   Right: TOOL: write_code, PARAMS: {"code": "import requests\\ndef run():\\n    ..."}

2. **FALLBACK LADDER** (follow in order):
   a. write_code → Use your training knowledge to write code directly
   b. If execution fails with a CONCRETE unknown (e.g. wrong endpoint, unknown field):
      Use check_registry to search for existing working functions
   c. If still stuck after 2 failed attempts: call delegate_research as LAST RESORT
   NEVER call delegate_research before attempting to write code first.

3. **SAFETY FIRST** — Every function must:
   - Wrap external calls in try/except
   - Return structured output: {"success": bool, "data": ..., "error": ...}
   - Include response.raise_for_status() after HTTP calls
   - Set reasonable timeouts on network calls

4. **DIAGNOSE BEFORE RETRY** — After execution failure:
   - Read the FULL error message carefully
   - Form a specific hypothesis about WHY it failed
   - Describe the fix in your THOUGHT before writing new code
   - Do NOT just retry the same code with trivial changes

5. **VERIFY BEFORE DONE** — You MUST have evidence the function works:
   - execute_code returned status=success with real output
   - If execution_success=False, you are NOT done

6. **REPORT FAITHFULLY** — In your DONE summary:
   - If code worked: describe what it produced
   - If code failed: say exactly what went wrong and what you tried
   - NEVER claim success without execution evidence

7. **AUTH HANDLING** — Never hardcode tokens:
   - Use auth dict from sandbox namespace: access_token = auth.get("access_token")
   - If auth is missing/expired, report auth_required in your DONE summary

8. **OUTPUT CONTRACT** — Store final result in 'result' variable:
   result = {"success": True, "data": <your_data>}

9. **MINIMUM COMPLEXITY** — Write the simplest code that solves the task.
   No unnecessary abstractions, classes, or helper functions.

10. **NO SCOPE CREEP** — Do exactly what was asked. If the task says "fetch user list",
    don't also build a caching layer and a retry system.

## WORKFLOW

1. check_registry — always check first. Reuse verified functions when available.
2. write_code — write your Python function.
3. execute_code — run in sandbox with the candidate_id from write_code.
4. If success → register_function → DONE.
5. If failure → read error, diagnose, fix, re-execute (max 2 repairs).
6. If auth error → DONE with auth_required note.
7. If stuck after repairs → delegate_research (LAST RESORT).
"""

    def __init__(
        self,
        agent_id: str,
        llm_client,
        sandbox=None,
        code_registry=None,
        code_generator=None,
        auth_manager=None,
        redis_store=None,
        blob_storage=None,
        max_repair_attempts: int = 2,
    ):
        self.sandbox = sandbox
        self.code_registry = code_registry
        self.code_generator = code_generator
        self.auth_manager = auth_manager
        self.max_repair_attempts = max_repair_attempts

        # CandidateStore — versioned in-memory record of each code attempt
        self._candidates: List[Dict[str, Any]] = []

        # Hard gate flag — delegate_research blocked until first write_code
        self._has_written_code: bool = False

        super().__init__(
            agent_id=agent_id,
            role="coder",
            llm_client=llm_client,
            redis_store=redis_store,
            blob_storage=blob_storage,
        )

    def get_system_prompt(self) -> str:
        return self.DEFAULT_SYSTEM_PROMPT

    # ─────────────────────────────────────────────────────────────
    # Tool Registration
    # ─────────────────────────────────────────────────────────────

    def setup_tools(self) -> None:
        self.register_tool(
            "check_registry",
            self._tool_check_registry,
            (
                "Look up existing verified functions in the registry before generating new code. "
                "Params: {\"task\": \"<natural language task>\", \"system\": \"<provider name>\"}"
            ),
            phase="thinking",
        )
        self.register_tool(
            "write_code",
            self._tool_write_code,
            (
                "Generate Python code for a task. Runs ValidationLayer automatically. "
                "Params: {\"code\": \"<python code>\", \"system\": \"<optional provider name>\"}"
            ),
            phase="thinking",
        )
        self.register_tool(
            "validate_code",
            self._tool_validate_code,
            (
                "Explicitly validate Python syntax and contract. "
                "Params: {\"code\": \"<python code>\"}"
            ),
            phase="thinking",
        )
        self.register_tool(
            "execute_code",
            self._tool_execute_code,
            (
                "Execute a validated code candidate in the sandbox. "
                "Params: {\"candidate_id\": <int>, \"code\": \"<python code>\"} "
                "— provide code directly if not using candidate_id."
            ),
            phase="action",
        )
        self.register_tool(
            "register_function",
            self._tool_register_function,
            (
                "Register a successfully executed function in the FunctionRegistry. "
                "Call ONLY after execute_code returns status=success. "
                "Params: {\"function_name\": \"<name>\", \"candidate_id\": <int>, "
                "\"system\": \"<provider>\", \"capabilities\": [\"...\"], "
                "\"description\": \"<what it does>\"}"
            ),
            phase="action",
        )
        self.register_tool(
            "delegate_research",
            self._tool_delegate_research,
            (
                "LAST RESORT — delegate to the researcher when you are stuck after multiple "
                "failed attempts. HARD GATE: you MUST call write_code at least once before "
                "this tool becomes available. "
                "Params: {\"question\": \"<what you need to know>\", \"context\": \"<what you've tried>\"}"
            ),
            phase="thinking",
        )

    # ─────────────────────────────────────────────────────────────
    # Tool: check_registry
    # ─────────────────────────────────────────────────────────────

    def _tool_check_registry(
        self,
        task: str = "",
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Registry-first reuse check."""
        if not self.code_registry:
            return {"found": False, "reason": "No registry configured."}

        try:
            matches = self.code_registry.semantic_search(task, limit=5)
            production = [
                m for m in matches
                if m.get("registry_stage") in ("verified", "golden")
            ]
            if system:
                system_matches = [m for m in production if m.get("system") == system]
                if system_matches:
                    production = system_matches
            if not production:
                return {"found": False, "message": "No verified functions found for this task."}

            top = production[0]
            code = self.code_registry.get_function_code(top["function_name"])

            return {
                "found": True,
                "function_name": top["function_name"],
                "system": top.get("system"),
                "stage": top.get("registry_stage"),
                "description": top.get("description"),
                "capabilities": top.get("capabilities", []),
                "success_count": top.get("success_count", 0),
                "code_preview": (code or "")[:400] if code else None,
                "message": (
                    f"Found verified function `{top['function_name']}` "
                    f"({top.get('success_count', 0)} successful executions). "
                    "Consider reusing it directly via execute_code."
                ),
            }
        except Exception as exc:
            logger.warning("CoderSubAgent.check_registry failed: %s", exc)
            return {"found": False, "reason": str(exc)}

    # ─────────────────────────────────────────────────────────────
    # Tool: write_code
    # ─────────────────────────────────────────────────────────────

    def _tool_write_code(
        self,
        code: str,
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Record + validate a code candidate."""
        self._has_written_code = True  # Unlock delegate_research gate

        candidate_id = len(self._candidates) + 1

        # Run ValidationLayer
        try:
            from jarviscore.execution.validation import ValidationLayer
            vl = ValidationLayer()
            vresult = vl.validate_pre_execution(code)
        except ImportError:
            vresult = None
            logger.warning("CoderSubAgent: ValidationLayer not available, skipping pre-validation")

        if vresult is not None and not vresult.is_valid:
            candidate = {
                "candidate_id": candidate_id,
                "code": code,
                "system": system,
                "status": "validation_failed",
                "validation_error": vresult.summary(),
                "ts": time.time(),
            }
            self._candidates.append(candidate)

            return {
                "candidate_id": candidate_id,
                "status": "validation_failed",
                "error": vresult.summary(),
                "issues": [
                    {"code": i.code, "message": i.message, "severity": i.severity.value}
                    for i in vresult.issues
                ],
                "instruction": (
                    "Fix the listed issues and call write_code again with corrected code. "
                    "Do NOT call execute_code until you have a candidate with status=validated."
                ),
            }

        candidate = {
            "candidate_id": candidate_id,
            "code": code,
            "system": system,
            "status": "validated",
            "ts": time.time(),
        }
        self._candidates.append(candidate)

        return {
            "candidate_id": candidate_id,
            "status": "validated",
            "length": len(code),
            "message": f"Code validated (candidate_id={candidate_id}). Call execute_code next.",
        }

    # ─────────────────────────────────────────────────────────────
    # Tool: validate_code
    # ─────────────────────────────────────────────────────────────

    def _tool_validate_code(self, code: str, **kwargs) -> Dict[str, Any]:
        """Explicit validation — syntax check + full ValidationLayer."""
        try:
            ast.parse(code)
        except SyntaxError as e:
            return {
                "valid": False,
                "error": f"SyntaxError at line {e.lineno}: {e.msg}",
                "line": e.lineno,
            }

        try:
            from jarviscore.execution.validation import ValidationLayer
            vresult = ValidationLayer().validate_pre_execution(code)
            return {
                "valid": vresult.is_valid,
                "summary": vresult.summary(),
                "issues": [
                    {"code": i.code, "message": i.message, "severity": i.severity.value}
                    for i in vresult.issues
                ],
            }
        except ImportError:
            return {"valid": True, "summary": "ValidationLayer unavailable — syntax OK only."}

    # ─────────────────────────────────────────────────────────────
    # Tool: execute_code
    # ─────────────────────────────────────────────────────────────

    async def _tool_execute_code(
        self,
        candidate_id: Optional[int] = None,
        code: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute code in the sandbox."""
        if not self.sandbox:
            return {"status": "error", "error": "No sandbox configured for this agent."}

        exec_code = code
        candidate = None

        if candidate_id is not None:
            candidate = self._get_candidate(candidate_id)
            if not candidate:
                return {
                    "status": "error",
                    "error": f"candidate_id={candidate_id} not found. "
                             "Call write_code first to create a candidate.",
                }
            if candidate.get("status") == "validation_failed":
                return {
                    "status": "error",
                    "error": (
                        f"candidate_id={candidate_id} failed validation. "
                        "Fix the issues and call write_code again."
                    ),
                }
            exec_code = candidate["code"]

        if not exec_code:
            return {"status": "error", "error": "No code provided to execute_code."}

        # Inject system bundle if needed
        if self.code_registry:
            try:
                systems = self.code_registry.detect_system_dependencies(exec_code)
                if systems:
                    exec_code = self.code_registry.prepare_code_with_bundle(
                        exec_code, systems[0]
                    )
            except Exception as exc:
                logger.warning("CoderSubAgent: bundle injection failed — %s", exc)

        # Build execution context (auth credentials)
        exec_context: Dict[str, Any] = {}

        auth_creds = None
        if hasattr(self, '_run_context') and self._run_context:
            auth_creds = self._run_context.get("_auth_credentials")

        if not auth_creds and self.auth_manager and candidate and candidate.get("system"):
            try:
                conn_id = await self.auth_manager.authenticate(
                    provider=candidate["system"],
                )
                strategy = await self.auth_manager.resolve_strategy(conn_id)
                auth_creds = {
                    "provider": candidate["system"],
                    "strategy_type": strategy.type,
                }
                if strategy.type == "oauth2":
                    auth_creds["access_token"] = strategy.credentials.get("access_token", "")
                elif strategy.type == "api_key":
                    auth_creds["access_token"] = strategy.credentials.get("api_key", "")
                elif strategy.type == "basic_auth":
                    auth_creds["username"] = strategy.credentials.get("username", "")
                    auth_creds["password"] = strategy.credentials.get("password", "")
            except Exception as auth_exc:
                logger.warning("CoderSubAgent: AuthManager failed: %s", auth_exc)

        if auth_creds:
            exec_context["auth"] = auth_creds

        start_ts = time.time()
        result = await self.sandbox.execute(exec_code, context=exec_context or None)
        exec_time = time.time() - start_ts

        # Classify auth errors
        if result.get("status") == "failure" and result.get("error"):
            auth_category = classify_auth_error(result["error"])
            if auth_category:
                result["auth_error_type"] = auth_category
                result["hitl_required"] = True
                result["hitl_reason"] = auth_category

        if candidate:
            candidate["status"] = result.get("status", "unknown")
            candidate["execution_time"] = exec_time
            candidate["error"] = result.get("error")

        result["execution_time"] = exec_time
        result["candidate_id"] = candidate_id

        if (
            self.code_registry
            and result.get("status") == "success"
            and candidate
            and candidate.get("function_name")
        ):
            try:
                self.code_registry.update_execution_stats(
                    candidate["function_name"],
                    success=True,
                    execution_time=exec_time,
                )
            except Exception:
                pass

        return result

    # ─────────────────────────────────────────────────────────────
    # Tool: register_function
    # ─────────────────────────────────────────────────────────────

    def _tool_register_function(
        self,
        function_name: str,
        candidate_id: Optional[int] = None,
        code: Optional[str] = None,
        system: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        description: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Promote a successfully executed candidate to the FunctionRegistry."""
        if not self.code_registry:
            return {"status": "error", "error": "No code_registry configured."}

        final_code = code
        if candidate_id is not None:
            candidate = self._get_candidate(candidate_id)
            if candidate:
                final_code = candidate.get("code", code)
                system = system or candidate.get("system")

        if not final_code:
            return {"status": "error", "error": "No code to register."}

        metadata = {
            "system": system,
            "capabilities": capabilities or [],
            "description": description,
            "agent_id": self.agent_id,
            "tags": [system] if system else [],
        }

        success = self.code_registry.register_function(
            function_name=function_name,
            function=final_code,
            metadata=metadata,
        )

        if success:
            if candidate_id is not None:
                candidate = self._get_candidate(candidate_id)
                if candidate:
                    candidate["function_name"] = function_name
                    candidate["status"] = "registered"

            return {
                "status": "registered",
                "function_name": function_name,
                "system": system,
                "message": (
                    f"Function `{function_name}` registered successfully. "
                    "It will graduate from CANDIDATE → VERIFIED → GOLDEN as it succeeds."
                ),
            }
        else:
            return {
                "status": "error",
                "error": f"Registry registration failed for `{function_name}`.",
            }

    # ─────────────────────────────────────────────────────────────
    # Tool: delegate_research (HARD GATE)
    # ─────────────────────────────────────────────────────────────

    def _tool_delegate_research(
        self,
        question: str,
        context: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Delegate a question to the researcher subagent.

        HARD GATE: This tool is blocked until write_code has been called
        at least once. The coder must attempt to solve the problem from
        training knowledge before delegating.
        """
        if not self._has_written_code:
            return {
                "status": "blocked",
                "error": (
                    "HARD GATE: You must call write_code at least once before "
                    "delegating to research. Write code from your training knowledge first. "
                    "Research is a LAST RESORT, not a first step."
                ),
            }

        # Signal to the kernel that research is needed.
        # The kernel will read signal_researcher from the output metadata
        # and dispatch a ResearcherSubAgent.
        return {
            "status": "delegated",
            "question": question,
            "context": context,
            "signal_researcher": True,
            "message": (
                "Research request queued for the Kernel. "
                "The Kernel will dispatch a Researcher and retry your task "
                "with the research findings. Call DONE now to hand off."
            ),
        }

    # ─────────────────────────────────────────────────────────────
    # Candidate Store Helpers
    # ─────────────────────────────────────────────────────────────

    def _get_candidate(self, candidate_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve candidate by ID (1-indexed)."""
        for c in self._candidates:
            if c.get("candidate_id") == candidate_id:
                return c
        return None

    @property
    def candidates(self) -> List[Dict[str, Any]]:
        """All candidates generated during this run (audit trail)."""
        return list(self._candidates)

    # ─────────────────────────────────────────────────────────────
    # Run Override
    # ─────────────────────────────────────────────────────────────

    async def run(self, task, context=None, max_turns=15, model=None, **kwargs):
        """Fresh candidate list per run — no state bleed between tasks."""
        self._candidates = []
        self._has_written_code = False
        self._run_context = context or {}
        try:
            return await super().run(task, context, max_turns, model, **kwargs)
        finally:
            self._run_context = {}
