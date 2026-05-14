"""
CoderSubAgent — Production-grade code generation and execution specialist.

Doctrine:
  1. CODE FROM KNOWLEDGE FIRST — write code from training data, don't research first
  2. FALLBACK LADDER — write_code → quick_api_search on concrete unknown → check_registry → delegate_research
  3. SAFETY FIRST — try/except everywhere, never fail silently
  4. DIAGNOSE BEFORE RETRY — form a hypothesis about WHY before next attempt
  5. VERIFY BEFORE DONE — must have evidence the function works (execution output)
  6. REPORT FAITHFULLY — if code failed, say so in the summary
  7. NO SCOPE CREEP — do exactly what was asked, nothing more
  8. RESPECT AUTH — never hardcode tokens; use auth dict from namespace
  9. REGISTER SUCCESS — promote working code to FunctionRegistry with {system}_{action} naming
  10. ASK FOR HELP — delegate_research when stuck, not when lazy
  11. REGISTRY NAMING — all registered functions MUST follow {system}_{action} convention
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
   b. If execution fails with a CONCRETE unknown (wrong endpoint, unknown field, unexpected response shape):
      Use quick_api_search or read_api_docs to look up the specific detail you need
   c. If still stuck: check_registry to search for existing working functions
   d. If stuck after 2 failed attempts + self-research: call delegate_research as ABSOLUTE LAST RESORT
   NEVER call delegate_research before attempting to write code AND self-research first.

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


7. **AUTH / NEXUS STANDARD** — ALL provider API calls MUST use `nexus_call()`:

   ```python
   # ✅ CORRECT — all auth handled by Nexus, no credentials in code
   response = await nexus_call("GET", "https://api.github.com/repos/my-org/my-repo")
   response = await nexus_call("POST", "https://api.stripe.com/v1/charges",
                               json={"amount": 1000, "currency": "usd"})
   response = await nexus_call("GET", "https://api.notion.com/v1/databases/{id}/query")

   if not response["ok"]:
       raise RuntimeError(f"API call failed: {response['status_code']} {response['body']}")
   data = response["json"]
   ```

   ```python
   # ❌ FORBIDDEN — never use requests/httpx directly for provider APIs
   import requests
   headers = {"Authorization": "Bearer ..."}  # VIOLATION — agent must never see credentials
   ```

   - `nexus_call(method, url, **kwargs)` is always available in the sandbox
   - It returns `{"ok": bool, "status_code": int, "body": str, "json": Any}`
   - If it raises RuntimeError, declare `auth_required=True` in your DONE summary
   - NEVER read `auth`, `token`, `api_key`, `access_token`, or any credential variable

8. **OUTPUT CONTRACT** — Store final result in 'result' variable:
   result = {"success": True, "data": <your_data>}

9. **MINIMUM COMPLEXITY** — Write the simplest code that solves the task.
   No unnecessary abstractions, classes, or helper functions.

10. **NO SCOPE CREEP** — Do exactly what was asked. If the task says "fetch user list",
    don't also build a caching layer and a retry system.

11. **REGISTRY NAMING** — When calling register_function:
    - function_name MUST follow {system}_{action} format (e.g., "airtable_create_table")
    - system parameter is REQUIRED (e.g., "airtable", "slack", "github")
    - description is REQUIRED (what the function does)
    - capabilities must include at least one tag
    Example: register_function(function_name="airtable_create_table",
                               system="airtable",
                               capabilities=["create_table"],
                               description="Create a new table in Airtable")

## WORKFLOW

1. check_registry — always check first. Reuse verified functions when available.
2. write_code — write your Python function.
3. execute_code — run in sandbox with the candidate_id from write_code.
4. If success → register_function → DONE.
5. If failure → read error, diagnose, quick_api_search/read_api_docs if concrete unknown, fix, re-execute (max 2 repairs).
6. If auth error → DONE with auth_required note.
7. If stuck after repairs + self-research → delegate_research (ABSOLUTE LAST RESORT).
"""

    def __init__(
        self,
        agent_id: str,
        llm_client,
        sandbox=None,
        code_registry=None,
        code_generator=None,
        auth_manager=None,
        search_client=None,
        redis_store=None,
        blob_storage=None,
        max_repair_attempts: int = 2,
    ):
        self.sandbox = sandbox
        self.code_registry = code_registry
        self.code_generator = code_generator
        self.auth_manager = auth_manager
        self.search_client = search_client
        self.max_repair_attempts = max_repair_attempts

        # CandidateStore — versioned in-memory record of each code attempt
        self._candidates: List[Dict[str, Any]] = []

        # Hard gate flag — delegate_research blocked until first write_code
        self._has_written_code: bool = False

        # URL content cache — session-scoped dedup for read_api_docs
        self._read_urls: set = set()
        self._current_task: str = ""

        super().__init__(
            agent_id=agent_id,
            role="coder",
            llm_client=llm_client,
            redis_store=redis_store,
            blob_storage=blob_storage,
            search_client=search_client,
            code_registry=code_registry,
        )

    def get_system_prompt(self) -> str:
        prompt = self.DEFAULT_SYSTEM_PROMPT
        if self.sandbox and hasattr(self.sandbox, "get_manifest"):
            manifest = self.sandbox.get_manifest()
            prompt += f"\\n\\n## SANDBOX ENVIRONMENT\\nThe following modules and globals are pre-loaded in your execution environment. Do NOT use `import` for these:\\n{manifest}"
        return prompt

    def _build_user_prompt(self, state: KernelState, context_block: str) -> str:
        """Add a coder-specific proof-of-work contract to the generic OODA prompt."""
        prompt = super()._build_user_prompt(state, context_block)
        has_execution = any(
            tool_res.tool_name == "execute_code" and tool_res.succeeded
            for tool_res in state.tool_history
        )
        if has_execution:
            return prompt

        validated_candidates = [
            tool_res.tool_output.get("candidate_id")
            for tool_res in state.tool_history
            if (
                tool_res.tool_name == "write_code"
                and tool_res.succeeded
                and isinstance(tool_res.tool_output, dict)
                and tool_res.tool_output.get("status") == "validated"
            )
        ]
        if validated_candidates:
            next_action = (
                f"You already have validated candidate_id={validated_candidates[-1]}. "
                "Your next response MUST call execute_code with that candidate_id."
            )
        else:
            next_action = (
                "Your next response MUST call write_code with executable Python code. "
                "After write_code validates it, call execute_code with the returned candidate_id."
            )

        return (
            f"{prompt}\n\n"
            "## CODER PROOF-OF-WORK GATE\n"
            "DONE/RESULT is disabled until execute_code has returned status=success.\n"
            f"{next_action}\n\n"
            "Valid next response format:\n"
            "THOUGHT: I need executable proof before completion.\n"
            "TOOL: write_code\n"
            "PARAMS: {\"code\": \"result = {'success': True, 'data': ...}\"}\n\n"
            "If you already have a candidate_id:\n"
            "THOUGHT: I have validated code and must execute it.\n"
            "TOOL: execute_code\n"
            "PARAMS: {\"candidate_id\": <id>}\n\n"
            "Do not emit DONE. Do not emit RESULT. Do not answer in prose."
        )

    # ─────────────────────────────────────────────────────────────
    # Completion Gate (Proof of Work)
    # ─────────────────────────────────────────────────────────────

    def _can_complete(
        self,
        state: KernelState,
        parsed: Dict[str, Any],
    ) -> tuple:
        """
        Enforce the "Verify Before Done" proof-of-work contract.
        """
        # Exemption: If the agent successfully delegated to research, it is handing
        # control back to the Kernel. It must be allowed to complete.
        if state.tool_history:
            last_tool = state.tool_history[-1]
            if last_tool.tool_name == "delegate_research" and last_tool.succeeded:
                return (True, "")

        # Scan history for execution proof
        has_executed = False
        last_success_output = None
        for tool_res in state.tool_history:
            if tool_res.tool_name == "execute_code" and tool_res.succeeded:
                has_executed = True
                last_success_output = tool_res.tool_output
            elif (
                tool_res.tool_name == "write_code"
                and tool_res.succeeded
                and isinstance(tool_res.tool_output, dict)
                and isinstance(tool_res.tool_output.get("execution_result"), dict)
                and tool_res.tool_output["execution_result"].get("status") == "success"
            ):
                has_executed = True
                last_success_output = tool_res.tool_output["execution_result"]

        if not has_executed:
            return (
                False,
                "PROOF OF WORK REQUIRED: You cannot call DONE without executing code first.\n"
                "You must use the `write_code` or `execute_code` tool to write and run actual Python code.\n"
                "Do NOT just output the answer in the RESULT block. You MUST execute a Python script that sets the `result` variable."
            )

        # Force the payload to be the actual sandbox execution result.
        if last_success_output is not None:
            parsed["result"] = last_success_output.get("output", last_success_output)

        return (True, "")

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
            "quick_api_search",
            self._tool_quick_api_search,
            (
                "Fast-twitch web search for API documentation when you hit a CONCRETE unknown "
                "(wrong endpoint, missing field, unexpected response). Max 3 results. "
                "Use ONLY after writing code and getting a specific error. "
                "Params: {\"query\": \"<search terms>\"}"
            ),
            phase="thinking",
        )
        self.register_tool(
            "read_api_docs",
            self._tool_read_api_docs,
            (
                "Read content from a single API documentation URL (Swagger, OpenAPI, reference). "
                "Truncated to 10KB. Each URL can only be read once per session. "
                "Params: {\"url\": \"<url>\"}"
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
                "function_name MUST follow {system}_{action} format. "
                "Params: {\"function_name\": \"<system_action>\", \"candidate_id\": <int>, "
                "\"system\": \"<provider>\", \"capabilities\": [\"...\"], "
                "\"description\": \"<what it does>\"}"
            ),
            phase="action",
        )
        self.register_tool(
            "delegate_research",
            self._tool_delegate_research,
            (
                "ABSOLUTE LAST RESORT — delegate to the researcher when you are stuck after multiple "
                "failed attempts AND self-research via quick_api_search/read_api_docs. "
                "HARD GATE: you MUST call write_code at least once before "
                "this tool becomes available. "
                "Params: {\"question\": \"<what you need to know>\", \"context\": \"<what you've tried>\"}"
            ),
            phase="thinking",
        )

    async def _execute_tool(self, tool_name: str, params: Dict) -> Dict[str, Any]:
        """Execute tools, auto-running validated code when runtime proof is required."""
        result = await super()._execute_tool(tool_name, params)
        if (
            tool_name != "write_code"
            or not isinstance(result, dict)
            or result.get("status") != "validated"
            or not self.sandbox
        ):
            return result

        execution_result = await self._tool_execute_code(candidate_id=result["candidate_id"])
        merged = dict(result)
        merged["execution_result"] = execution_result
        if execution_result.get("status") == "success":
            merged["status"] = "success"
            merged["output"] = execution_result.get("output")
            merged["_auto_complete"] = True
            merged["message"] = (
                f"Code validated and executed successfully (candidate_id={result['candidate_id']})."
            )
        else:
            merged["status"] = "error"
            merged["error"] = execution_result.get("error", "Code execution failed.")
        return merged

    # ─────────────────────────────────────────────────────────────
    # Tool: check_registry
    # ─────────────────────────────────────────────────────────────

    async def _tool_check_registry(
        self,
        task: str = "",
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Registry-first reuse check."""
        if not self.code_registry:
            return {"found": False, "reason": "No registry configured."}

        try:
            from jarviscore.execution.intent_normalizer import IntentNormalizer
            normalizer = IntentNormalizer(self.llm_client)
            normalized_task = await normalizer.normalize(task)

            matches = self.code_registry.semantic_search(normalized_task, limit=5)
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

        contract_text = (
            f"{getattr(self, '_current_task', '')}\n"
            f"{(getattr(self, '_run_context', {}) or {}).get('system_prompt', '')}"
        ).lower()
        if "blob_path" in contract_text and "blob_path(" not in code:
            candidate = {
                "candidate_id": candidate_id,
                "code": code,
                "system": system,
                "status": "validation_failed",
                "validation_error": "Contract requires blob_path(), but generated code does not call it.",
                "ts": time.time(),
            }
            self._candidates.append(candidate)
            return {
                "candidate_id": candidate_id,
                "status": "validation_failed",
                "error": "Contract requires blob_path(), but generated code does not call it.",
                "issues": [
                    {
                        "code": "missing_blob_path",
                        "message": (
                            "The task or system prompt explicitly requires blob_path(). "
                            "Rewrite the code to call dest = blob_path(<filename>) and write to dest."
                        ),
                        "severity": "error",
                    }
                ],
                "instruction": (
                    "Call write_code again with corrected code that uses blob_path(...). "
                    "Do NOT call execute_code for this candidate."
                ),
            }

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

        # Build execution context — safe task metadata only.
        # Credentials are NEVER injected here. The sandbox receives
        # _nexus_connection_id (opaque) via _run_context, which is then
        # used exclusively by nexus_call() inside the sandbox.
        exec_context: Dict[str, Any] = {}
        if hasattr(self, '_run_context') and self._run_context:
            SAFE_KEYS = {"task", "system", "workflow_id", "step_id",
                         "prior_outputs", "registry_candidate", "_hint",
                         "_nexus_connection_id", "_nexus_provider"}
            for k in SAFE_KEYS:
                if k in self._run_context:
                    exec_context[k] = self._run_context[k]

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

        # Evaluator hook: check semantic success
        if result.get("status") == "success":
            output = result.get("output", {})
            if isinstance(output, dict):
                if output.get("success") is False or output.get("status") in ["failure", "error"]:
                    result["status"] = "failure"
                    result["error"] = output.get("error", output.get("reason", "Semantic failure: Task executed but returned a failure status."))
                    result["semantic_success"] = False

        # Pydantic schema validation
        output_schema = (getattr(self, '_run_context', {}) or {}).get("output_schema")
        if result.get("status") == "success" and output_schema:
            try:
                output_data = result.get("output", {})
                if isinstance(output_data, dict) and "data" in output_data:
                    data_to_validate = output_data["data"]
                else:
                    data_to_validate = output_data
                output_schema.model_validate(data_to_validate)
            except Exception as e:
                result["status"] = "failure"
                result["error"] = f"Output schema validation failed: {str(e)}"
                result["semantic_success"] = False

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
            except Exception as exc:
                logger.warning(
                    "Failed to update execution stats for %s: %s",
                    candidate["function_name"],
                    exc,
                )

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

        # ── Naming enforcement (Coder-side) ──
        # The registry also does soft-correction, but the Coder should use
        # the correct {system}_{action} convention from the start.
        if system:
            from jarviscore.execution.code_registry import FunctionRegistry
            function_name = FunctionRegistry.validate_function_name(
                function_name, system
            )

        if not description:
            return {
                "status": "error",
                "error": (
                    "description is REQUIRED for register_function. "
                    "Provide a brief description of what the function does."
                ),
            }

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
    # Tool: quick_api_search (Self-Research)
    # ─────────────────────────────────────────────────────────────

    async def _tool_quick_api_search(
        self,
        query: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Fast-twitch web search for API documentation.

        Restricted to 3 results to prevent context bloat. Smart truncation
        to ~8KB around query keywords. Ported from IA CoderAgent's
        quick_internet_search pattern.
        """
        if not self.search_client:
            return {
                "status": "unavailable",
                "message": (
                    "No search_client configured. Try check_registry "
                    "or delegate_research instead."
                ),
            }

        logger.info("[CODER] quick_api_search: %s", query)

        try:
            results = self.search_client.search(query, max_results=3)
            if hasattr(results, "__await__"):
                results = await results

            # If search_client supports extract_content, get the first result's content
            extracted = {}
            if hasattr(self.search_client, "extract_content") and results:
                first_url = None
                if isinstance(results, list) and results:
                    first_url = results[0].get("url") if isinstance(results[0], dict) else None
                elif isinstance(results, dict):
                    items = results.get("results", results.get("search_results", []))
                    if items and isinstance(items, list):
                        first_url = items[0].get("url") if isinstance(items[0], dict) else None

                if first_url:
                    try:
                        content_result = self.search_client.extract_content(
                            first_url, max_length=10000
                        )
                        if hasattr(content_result, "__await__"):
                            content_result = await content_result

                        if isinstance(content_result, dict) and content_result.get("success"):
                            content = content_result.get("content", "")

                            # Smart truncation: find the most keyword-dense 8KB window
                            if content and len(content) > 8000:
                                keywords = [
                                    w.lower()
                                    for w in query.split()
                                    if len(w) > 3
                                    and w.lower()
                                    not in {
                                        "how", "the", "and", "for", "with",
                                        "api", "rest", "what", "does",
                                    }
                                ]
                                best_idx, max_matches = 0, 0
                                chunk_size = 4000
                                for i in range(0, len(content) - chunk_size, chunk_size // 2):
                                    chunk = content[i : i + chunk_size].lower()
                                    matches = sum(1 for k in keywords if k in chunk)
                                    if matches > max_matches:
                                        max_matches = matches
                                        best_idx = i

                                start = max(0, best_idx - 2000)
                                end = min(len(content), start + 8000)
                                prefix = "... [TRUNCATED] ...\n" if start > 0 else ""
                                suffix = "\n... [TRUNCATED]" if end < len(content) else ""
                                content = prefix + content[start:end] + suffix

                            extracted = {
                                "url": first_url,
                                "title": content_result.get("title", ""),
                                "content": content,
                            }
                    except Exception as exc:
                        logger.debug("quick_api_search extract_content failed: %s", exc)

            return {
                "status": "success",
                "query": query,
                "snippets": results if isinstance(results, list) else [],
                "extracted_content": extracted,
            }

        except Exception as exc:
            logger.warning("quick_api_search failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    # ─────────────────────────────────────────────────────────────
    # Tool: read_api_docs (Self-Research)
    # ─────────────────────────────────────────────────────────────

    async def _tool_read_api_docs(
        self,
        url: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Read content from a single API documentation URL.

        Session-scoped dedup prevents re-reading the same URL. Content
        truncated to 10KB. Ported from ResearcherSubAgent._tool_read_url.
        """
        if not self.search_client:
            return {
                "status": "unavailable",
                "message": "No search_client configured.",
            }

        # Session dedup — don't re-read within the same run
        if url in self._read_urls:
            return {
                "status": "cached",
                "message": (
                    f"URL already read in this session. "
                    "Use the information from the previous read."
                ),
            }

        logger.info("[CODER] read_api_docs: %s", url)

        try:
            if not hasattr(self.search_client, "extract_content"):
                return {
                    "status": "unavailable",
                    "message": "search_client does not support extract_content().",
                }

            result = self.search_client.extract_content(url, max_length=12000)
            if hasattr(result, "__await__"):
                result = await result

            self._read_urls.add(url)

            if isinstance(result, dict):
                if result.get("success"):
                    content = result.get("content", "")
                    if len(content) > 10000:
                        content = content[:10000] + "\n\n... [truncated at 10KB]"
                    return {
                        "status": "success",
                        "title": result.get("title", ""),
                        "content": content,
                        "word_count": result.get("word_count", 0),
                    }
                else:
                    return {
                        "status": "error",
                        "error": result.get("error", "Extraction failed"),
                    }
            else:
                content = str(result)
                if len(content) > 10000:
                    content = content[:10000] + "\n\n... [truncated at 10KB]"
                return {"status": "success", "content": content}

        except Exception as exc:
            logger.warning("read_api_docs failed: %s", exc)
            return {"status": "error", "error": str(exc)}

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
        self._read_urls = set()
        self._current_task = str(task)
        self._run_context = context or {}
        try:
            return await super().run(task, context, max_turns, model, **kwargs)
        finally:
            self._current_task = ""
            self._run_context = {}
