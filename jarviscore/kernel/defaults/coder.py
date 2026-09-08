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
from typing import Any, Dict, List, Optional, Tuple

from jarviscore.kernel.subagent import BaseSubAgent
from jarviscore.kernel.gate import GateEvidence
from jarviscore.kernel.state import KernelState

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Auth Outcome
# ─────────────────────────────────────────────────────────────────


def classify_access_failure(
    access_failure: Optional[Dict[str, Any]],
    connection_state: Optional[str] = None,
) -> Optional[str]:
    """Name what went wrong at the credential boundary, from what it recorded.

    Reads the boundary's own statement rather than the rendered message. The
    message was matched against substrings before, which classified "Created 401
    contacts successfully" as an authentication failure and asked a human to log
    in after a run that worked.

    A provider rejecting a credential is evidence, not a verdict: whether that
    means "never connected" or "the token went stale" is answered by what the
    vault holds, so the state is asked for rather than guessed.
    """
    if not access_failure:
        return None
    kind = access_failure.get("kind")
    if kind == "no_usable_credential":
        return "missing_auth"
    if kind == "destination_not_owned_by_provider":
        return None  # a routing mistake, not an access grant a human can give
    if kind == "provider_rejected_credential":
        return "expired_token" if connection_state == "connected" else "missing_auth"
    return None


def _produced_output(output: Any) -> bool:
    """Did the run leave anything a caller could read?

    The sandbox envelope (marked by ``success``) always reports its own
    bookkeeping — timings, file lists — so its presence says only that code ran.
    Answering requires a returned value, stdout, or a written file. Anything the
    sandbox hands back that is not that envelope is already the result itself.
    """
    if output is None:
        return False
    if not isinstance(output, dict):
        return str(output).strip() != ""
    if "success" not in output:
        return bool(output)
    return (
        output.get("data") is not None
        or bool(str(output.get("stdout") or "").strip())
        or bool(output.get("files_created") or output.get("files_modified"))
    )


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

## WHY YOU EXIST (read this first — it explains every rule below)

Other agents reason in language. You are different: your value is *proof*. An
answer you worked out in your head is a guess to the rest of the system, no
matter how confident you are. An answer produced by code you executed is a
verified fact the whole swarm can trust and reuse. So your instinct is never
"I know this" — it is "let me run it and see." Even a task you could do in your
head (a sum, a sort, a date calculation) goes through code, because the point
is not the number, it is that the number came from a run anyone can reproduce.

A result that never touched the sandbox is not a result. If you catch yourself
about to report an answer you computed mentally, stop and write the code that
proves it — that is the entire job.

## THE CATALOGUE (this is how the swarm stops re-solving the same problem)

The FunctionRegistry holds atoms: functions that already ran against a real API
and worked, scoped to the provider they call. It is a ratchet — every task that
succeeds should leave the next one less work.

When the provider for a task is known — because the task named a connected
system, or because the registry already matched a proven atom to it — that
provider's capabilities are already in your tool list, named for what they do —
`hubspot_list_contacts`, `slack_send_message`. They run where the credentials
are, so you call one the way you call any other tool and get a result; you never
handle a token and never see how the call was authenticated.

Call one when it does what the task needs. Writing code to make a request that
is already sitting in your tools is slower, unproven, and leaves a second
version of something that already works.

## WHEN A PROVIDER IS REGISTERED BUT NOBODY HAS CONNECTED

Registering a provider's app and connecting an account are two different events.
The first is done by whoever set the system up; the second needs a person to
consent once, and until they do there is no token and nothing can be signed.

When that is the case you will have `request_access` instead of that provider's
capabilities. Call it when the task actually needs that provider. It shows a
human the consent link and waits for them, so the cost of asking is time, not
tokens. When it returns, the capabilities are in your tools and you carry on
with the task in the same run.

Do not write code to work around a missing connection, and do not report the
provider as unavailable without asking. Both leave the human with a dead end
they could have cleared with one click.

## WHEN YOU CANNOT DO IT

Say what the task needed and what stopped you, in the terms of the person who
asked. They asked about their customers, their files, their messages — so the
answer is "the Slack account is not connected yet", not a report on environment
variables, gateway URLs or container state.

How this deployment is wired is not your subject and not your finding. If you
notice something an operator would need to fix, one plain sentence names it and
you stop; do not go looking for it, do not probe configuration to confirm it,
and never hand back a diagnosis of the plumbing as if it were the work.

The registry also holds atoms that are not yet callable, and `check_registry`
finds them. A `candidate` has been dry-run but never confirmed against a live
API, so it is readable code rather than a tool — read it, start from it, and
prove it in the sandbox. That run is what makes it callable for everyone after.

Writing to it, after you succeed:

- When you write new code that executes successfully against a provider, call
  `register_function` to keep it, with the `system` set to that provider. It
  enters as a candidate, becomes verified on its first success and golden after
  five, and from then on it is what the next agent finds instead of starting
  from a blank file.
- Take `auth_info` as the first parameter and authenticate with it, the way the
  catalogue does, so what you wrote can become a callable capability rather than
  a snippet.
- Name it for what it does to what: `hubspot_list_contacts`, not `run_task` or
  `main`. The name is how it will be found.
- Code that only reshapes local data is not worth keeping. An atom earns its
  place by reaching a system.

## CRITICAL RULES (read all before acting)

1. **CODE, DON'T META-CODE** — Produce actual Python functions, not plans or descriptions.
   Wrong: "I would write a function that calls the API..."
   Right: TOOL: write_code, PARAMS: {"code": "import requests\\ndef run():\\n    ..."}

2. **FALLBACK LADDER** (follow in order):
   a. check_registry when the task names a system — reuse beats rewriting
   b. write_code → Use your training knowledge to write code directly
   c. If execution fails with a CONCRETE unknown (wrong endpoint, unknown field, unexpected response shape):
      Use quick_api_search or read_api_docs to look up the specific detail you need
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

   `nexus_call` is ASYNC, and the sandbox cannot execute top-level `await`.
   Put every `await nexus_call(...)` inside `async def main()` and RETURN your
   result dict from it; the sandbox detects async code, awaits `main()`, and
   uses its return value as the output.

   ```python
   # ✅ CORRECT — all auth handled by Nexus, no credentials in code
   async def main():
       response = await nexus_call("GET", "https://api.github.com/repos/my-org/my-repo")
       if not response["ok"]:
           raise RuntimeError(f"API call failed: {response['status_code']} {response['body']}")
       return {"success": True, "data": response["json"]}
   ```

   ```python
   # ❌ FORBIDDEN — top-level await is a SyntaxError in the sandbox
   response = await nexus_call("GET", "https://api.github.com/...")

   # ❌ FORBIDDEN — calling without await returns a coroutine, not the response
   response = nexus_call("GET", "https://api.github.com/...")

   # ❌ FORBIDDEN — never use requests/httpx directly for provider APIs
   import requests
   headers = {"Authorization": "Bearer ..."}  # VIOLATION — agent must never see credentials
   ```

     - `nexus_call(method, url, **kwargs)` is always available in the sandbox
     - For work spanning connected systems, route each call explicitly:
         `await nexus_call("GET", url, provider="gmail")`. The trusted parent
         resolves that provider's opaque handle and host policy; no credential map
         enters your code. Never send one provider's call under another provider.
   - It returns `{"ok": bool, "status_code": int, "body": str, "json": Any}`
   - If it raises RuntimeError, declare `auth_required=True` in your DONE summary
   - NEVER read `auth`, `token`, `api_key`, `access_token`, or any credential variable

8. **OUTPUT CONTRACT** — Store final result in 'result' variable:
   result = {"success": True, "data": <your_data>}
   In async code, RETURN that dict from `async def main()` instead; the
   sandbox uses main()'s return value as the output.

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
        offered = set(getattr(self, "_atom_tools", ()))
        has_execution = any(
            (tool_res.tool_name == "execute_code" or tool_res.tool_name in offered)
            and tool_res.succeeded
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
        elif offered:
            # Mandating write_code here is what sent an agent to reimplement a
            # capability it had already been given.
            next_action = (
                f"This system's proven capabilities are available to you: "
                f"{', '.join(sorted(offered))}. Call one if it does what the task "
                "needs. Otherwise your next response MUST call write_code with "
                "executable Python code, then execute_code with the returned "
                "candidate_id."
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
        execute_calls = 0
        write_calls = 0
        atom_calls = 0
        for tool_res in state.tool_history:
            if tool_res.tool_name == "execute_code":
                execute_calls += 1
            elif tool_res.tool_name == "write_code":
                write_calls += 1
            elif tool_res.tool_name in getattr(self, "_atom_tools", ()):
                # A capability call is a run against a live provider, which is
                # the thing this gate exists to require. Demanding write_code as
                # well would mean an agent that used the catalogue correctly gets
                # told to go and reimplement it.
                atom_calls += 1
                if tool_res.succeeded:
                    has_executed = True
                    last_success_output = tool_res.tool_output
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
                GateEvidence(
                    check="proof_of_work",
                    requirement=(
                        "one execute_code call that succeeded, one write_code call "
                        "whose execution_result reports success, or one successful "
                        "capability call against the declared system"
                    ),
                    observed={
                        "tool_calls": len(state.tool_history),
                        "execute_code_calls": execute_calls,
                        "write_code_calls": write_calls,
                        "capability_calls": atom_calls,
                        "successful_executions": 0,
                    },
                ),
            )

        # The gate checks that proof exists. It does not replace the answer with
        # it: overwriting RESULT with the sandbox return value discarded the
        # agent's conclusion at the one moment it had one, so a Drive listing
        # reached the person as a dict of ids however well the agent had read it.
        # The proof stays reachable as evidence for anyone who wants it.
        if last_success_output is not None:
            parsed["evidence"] = last_success_output.get("output", last_success_output)

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
            merged["message"] = (
                f"Code validated and executed successfully (candidate_id={result['candidate_id']})."
            )
            # The result is the agent's to read, not the run's to return. Ending
            # the loop here handed callers the sandbox's raw return value as the
            # answer, with the agent never having looked at it: a Drive listing
            # arrived as a dict of ids instead of "your three most recent files
            # are". Proof is still required, by _can_complete, at DONE.
            if _produced_output(execution_result.get("output")):
                merged["message"] += (
                    " Read the result, then answer the task in your own words with "
                    "DONE. If the task needs more, continue."
                )
            else:
                merged["message"] += (
                    " The run returned no value and printed nothing, so there is no "
                    "result to report yet. Return your findings from main() (or print "
                    "them), then finish — or, if the task genuinely has no output, "
                    "finish with DONE and say so explicitly."
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

            # The declared provider is not a preference to be outweighed. An atom
            # for another system is not a weaker match, it is the wrong API — and
            # semantic search will happily rank a verified atom from one CRM above
            # a candidate from the one actually being asked about.
            declared = system or (getattr(self, "_run_context", None) or {}).get("system")
            if not declared:
                # Ranking across every provider let word overlap choose one, and
                # it is not a judgement worth trusting to substring counting.
                return {
                    "found": False,
                    "message": (
                        "Name the provider to search within, as system=<name>. "
                        "Which API a task needs is yours to decide; the registry "
                        "only says what already works for a provider you name."
                    ),
                }
            matches = [m for m in matches if m.get("system") == declared]
            if not matches:
                return {
                    "found": False,
                    "system": declared,
                    "message": (
                        f"No function in the registry targets {declared}. "
                        "Write one, and register it against that system so the "
                        "next agent finds it."
                    ),
                }

            # Within the right system, stage decides: something confirmed against a
            # live API beats something only dry-run.
            production = [
                m for m in matches
                if m.get("registry_stage") in ("verified", "golden")
            ]
            top = (production or matches)[0]
            code = self.code_registry.get_function_code(top["function_name"])
            stage = top.get("registry_stage")

            # Surface the reuse candidate's identity in the envelope (#88).
            getattr(self, "_dispatch_metadata", {}).setdefault(
                "registry_match", top["function_name"]
            )

            if stage in ("verified", "golden"):
                message = (
                    f"`{top['function_name']}` is {stage} with "
                    f"{top.get('success_count', 0)} successful execution(s) against a live API."
                )
            else:
                message = (
                    f"`{top['function_name']}` is a {stage}: written for this call and "
                    "dry-run, never confirmed against a live API. Executing it "
                    "successfully is what promotes it to verified."
                )

            return {
                "found": True,
                "function_name": top["function_name"],
                "system": top.get("system"),
                "stage": stage,
                "description": top.get("description"),
                "capabilities": top.get("capabilities", []),
                "success_count": top.get("success_count", 0),
                "code": code,
                "message": message,
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

        # Often the agent is the first to work out which provider the task needs.
        # Offerings are refreshed here so a proven atom or a missing consent is
        # discovered at that moment rather than after a failed call.
        access_note = self._refresh_offerings_for(system)

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

        result = {
            "candidate_id": candidate_id,
            "status": "validated",
            "length": len(code),
            "message": f"Code validated (candidate_id={candidate_id}). Call execute_code next.",
        }
        if access_note:
            result["system_access"] = access_note
        return result

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
                         "prior_outputs", "registry_candidate",
                         "_nexus_connection_id", "_nexus_provider"}
            for k in SAFE_KEYS:
                if k in self._run_context:
                    exec_context[k] = self._run_context[k]

        start_ts = time.time()
        result = await self.sandbox.execute(exec_code, context=exec_context or None)
        exec_time = time.time() - start_ts


        # Classify auth outcomes from what the credential boundary recorded.
        access_failure = result.get("access_failure")
        if access_failure:
            provider = access_failure.get("provider")
            auth_category = classify_access_failure(
                access_failure, self._connection_state(provider).value
            )
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

        # Both outcomes are evidence about the atom. A refusal at the credential
        # boundary is not: the atom never ran, so it says nothing about it.
        if (
            self.code_registry
            and candidate
            and candidate.get("function_name")
            and result.get("status") in ("success", "failure")
            and not result.get("access_failure")
        ):
            try:
                self.code_registry.update_execution_stats(
                    candidate["function_name"],
                    success=result["status"] == "success",
                    execution_time=exec_time,
                    error_type=result.get("error_type"),
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
        self._registered_this_run = bool(success)

        if success:
            # Registry identity for the result envelope (issue #88): the
            # promoted function's name IS its registry id.
            getattr(self, "_dispatch_metadata", {})["function_id"] = function_name
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

    def _save_subagent_state(self, state: KernelState) -> None:
        state.internal_variables["_coder_candidates"] = self._candidates

    def _restore_subagent_state(self, state: KernelState) -> None:
        self._candidates = list(state.internal_variables.get("_coder_candidates") or [])

    # ─────────────────────────────────────────────────────────────
    # Run Override
    # ─────────────────────────────────────────────────────────────

    async def run(self, task, context=None, max_turns=15, model=None, **kwargs):
        """Fresh candidate list per run — no state bleed between tasks."""
        self._candidates = []
        self._has_written_code = False
        self._read_urls = set()
        self._registered_this_run = False
        self._current_task = str(task)
        self._run_context = context or {}
        await self._sync_connections()
        self._prepare_access(self._resolved_system())
        try:
            return await super().run(task, context, max_turns, model, **kwargs)
        finally:
            self._current_task = ""
            self._run_context = {}

    def _resolved_system(self) -> Optional[str]:
        """The system whose capabilities belong in this dispatch.

        A declared system is the task naming a provider. A registry candidate is
        the registry having already found the provider's verified atom for this
        task. Both identify the same thing, so both make the atoms callable.
        Only the declared one carries credential-gate semantics; that stays in
        the kernel and is deliberately not read here.
        """
        declared = self._run_context.get("system")
        if declared:
            return str(declared)
        candidate = self._run_context.get("registry_candidate") or {}
        resolved = candidate.get("system") if isinstance(candidate, dict) else None
        return str(resolved) if resolved else None

    def _valid_atoms(self, system: Optional[str]) -> Dict[str, Any]:
        """The atoms for a system that are actually callable in their current shape."""
        from jarviscore.execution.atom_contract import read_contract

        atoms: Dict[str, Any] = {}
        if not system or not self.code_registry:
            return atoms
        for entry in self.code_registry.get_functions_by_system(system):
            name = entry.get("function_name")
            code = self.code_registry.get_function_code(name) if name else None
            if not code:
                continue
            contract = read_contract(code, system=system, expected_name=name)
            atom = contract.atom
            # Only the current shape is offered; a legacy atom cannot be called.
            if not contract.ok or atom is None or atom.legacy:
                continue
            atoms[name] = atom
        return atoms

    def _offer_system_capabilities(self, system: Optional[str]) -> None:
        """Register the connected system's atoms as tools for this dispatch.

        A capability the agent has to remember to go looking for is one it will
        sometimes skip, and it did. These arrive the way every other tool does,
        so using them is the default path rather than a decision.
        """
        for name in getattr(self, "_atom_tools", ()):
            self._tools.pop(name, None)
        self._atom_tools = []
        self._atoms = self._valid_atoms(system)
        if not system:
            return

        for name, atom in self._atoms.items():
            self.register_tool(
                name,
                self._atom_tool(name),
                f"{atom.describe()} Runs against {system} with "
                "credentials resolved outside the sandbox; you never handle them.",
                phase="action",
            )
            self._atom_tools.append(name)

        if self._atom_tools:
            self._log.info(
                "Offering %d %s capability(ies): %s",
                len(self._atom_tools), system, ", ".join(self._atom_tools),
            )

    async def _sync_connections(self) -> None:
        """Learn what the gateway holds before deciding what to offer.

        Offerings are decided synchronously during the run, so the gateway is
        asked once here. Without it a consent completed in the previous run is
        invisible and the agent asks for access it already has.
        """
        manager = self.auth_manager
        if manager is None or not hasattr(manager, "discover_all"):
            return
        try:
            from jarviscore.nexus.store import ConnectionState, get_store

            store = get_store()
            providers = store.list()
            await manager.discover_all(providers)
            self._run_context["connected_providers"] = sorted(
                provider for provider in providers
                if manager.is_connected(provider)
                or store.connection_state(provider) is ConnectionState.CONNECTED
            )
        except Exception as exc:
            self._log.debug("Connection sync unavailable: %s", exc)

    def _connection_state(self, system: Optional[str]):
        from jarviscore.nexus.store import ConnectionState, get_store

        if not system:
            return ConnectionState.ABSENT
        # The gateway knows what has been connected; the vault knows what was
        # registered here. A token that landed elsewhere lives only in the first.
        connected_at_gateway = getattr(self.auth_manager, "is_connected", None)
        if callable(connected_at_gateway) and connected_at_gateway(system):
            return ConnectionState.CONNECTED
        try:
            return get_store().connection_state(system)
        except Exception as exc:
            self._log.debug("Connection state unavailable for %s: %s", system, exc)
            return ConnectionState.ABSENT

    def _connection_handle(self, system: str) -> str:
        """What the sandbox should call through for this system."""
        manager = self.auth_manager
        found = manager.connection_handle(system) if manager is not None and hasattr(manager, "connection_handle") else None
        # Local-vault mode: the handle is the provider name.
        return found if isinstance(found, str) and found else system

    def _prepare_access(self, system: Optional[str]) -> None:
        """Offer what this system can do right now, and nothing it cannot.

        Offering an atom for a provider with no usable credential produces a
        confident call that cannot be signed, which reads as a broken capability
        rather than a missing connection.
        """
        from jarviscore.nexus.store import ConnectionState

        self._offered_system = system
        connected = self._connection_state(system) is ConnectionState.CONNECTED
        self._offer_system_capabilities(system if connected else None)
        self._offer_access_request(system)
        if connected and system:
            # Keeps the credential and the capability pointing at the same provider.
            if self._run_context.get("_nexus_provider") != system:
                self._run_context["_nexus_connection_id"] = self._connection_handle(system)
                self._run_context["_nexus_provider"] = system

    def _refresh_offerings_for(self, system: Optional[str]) -> Optional[str]:
        """Re-offer for a system named after the run began; note what changed."""
        if not system or system == getattr(self, "_offered_system", None):
            return None
        self._prepare_access(system)
        if self._atom_tools:
            return (
                f"{system} has {len(self._atom_tools)} proven capabilities, now in "
                f"your tools: {', '.join(self._atom_tools)}. Prefer them over code "
                "that repeats what they already do."
            )
        if self._access_tools:
            return (
                f"{system}'s app is registered but no account is connected, so no "
                "call to it can be signed, and its capabilities are held back "
                "until one is. request_access is now in your tools; it asks a "
                "human to consent and returns when they have."
            )
        return None

    def _providers_awaiting_consent(self) -> List[Tuple[str, int]]:
        """Registered providers missing usable credentials, and what each unlocks.

        Two sources, because consent is lost two ways: an app registered and
        never connected (the vault knows), or a connection the broker has since
        marked as needing re-consent (the auth manager knows).
        """
        pending: Dict[str, int] = {}
        connected_at_gateway = getattr(self.auth_manager, "is_connected", lambda _p: False)
        try:
            from jarviscore.nexus.store import get_store
            store = get_store()
            for provider in store.list():
                # The vault holds only the app; the token may have landed at the
                # gateway. Asking again for access already granted is the exact
                # thing this whole path exists to stop.
                from jarviscore.nexus.store import ConnectionState
                state_fn = getattr(store, "connection_state", None)
                awaiting = (
                    state_fn(provider) is ConnectionState.REGISTERED
                    if state_fn is not None
                    else store.needs_consent(provider)
                )
                if awaiting and not connected_at_gateway(provider):
                    pending[provider] = len(self._valid_atoms(provider))
        except Exception as exc:
            self._log.debug("Consent states unavailable: %s", exc)
        manager = self.auth_manager
        if manager is not None and hasattr(manager, "providers_needing_attention"):
            for provider in manager.providers_needing_attention():
                pending.setdefault(provider, len(self._valid_atoms(provider)))
        return sorted(pending.items())

    def _offer_access_request(self, system: Optional[str] = None) -> None:
        """Offer a way to get connected, for anything that is one consent away.

        Not keyed to a system resolved before the run: the agent is often the
        first to work out which provider a task needs, and a capability it can
        only ask for after naming it is one it will never think to ask for.
        """
        for name in getattr(self, "_access_tools", ()):
            self._tools.pop(name, None)
        self._access_tools = []

        pending = self._providers_awaiting_consent()
        if not pending:
            return
        described = ", ".join(
            f"{provider} ({count} capabilities)" for provider, count in pending
        )
        self.register_tool(
            "request_access",
            self._access_tool(),
            "Ask a human to connect an account for a provider whose app is "
            f"registered but which nobody has consented to yet: {described}. "
            "Nothing can be signed for these, so their capabilities are held "
            "back. Pass system=<name>. This shows the human a consent link and "
            "waits for them; when it returns, that provider's capabilities are "
            "in your tools and you continue with the task.",
            phase="action",
        )
        self._access_tools = ["request_access"]

    def _access_tool(self):
        async def request_access(system: str):
            if not system:
                return {
                    "status": "error",
                    "error": "request_access needs the system to connect.",
                    "semantic_error": "SYSTEM_NOT_NAMED",
                }
            if not self.auth_manager:
                self._log.error(
                    "%s needs a consent flow but no Nexus gateway is configured "
                    "to run one; set NEXUS_GATEWAY_URL.", system,
                )
                return {
                    "status": "error",
                    "error": (
                        f"Nobody can approve access to {system} from here, so it "
                        "cannot be used for this task. Say plainly that the task "
                        f"needs {system} and that access to it is unavailable."
                    ),
                    "semantic_error": "NO_CONSENT_CHANNEL",
                }
            try:
                return_url = self.auth_manager.return_url
                run_id = self._run_context.get("run_id")
                if run_id:
                    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
                    parsed = urlparse(return_url)
                    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
                    query["run_id"] = str(run_id)
                    return_url = urlunparse(parsed._replace(query=urlencode(query)))
                connection_id, auth_url = await self.auth_manager.begin_authentication(
                    system, return_url=return_url
                )
                from jarviscore.nexus.store import get_store
                store = get_store()
                profile = store.get(system) if hasattr(store, "get") else None
                auth_type = str((profile or {}).get("auth_type") or "oauth2")
                if auth_type == "oauth2":
                    await self.auth_manager.flow_handler.present_auth_url(
                        auth_url, system, connection_id=connection_id,
                        context=self._run_context,
                    )
                else:
                    state, schema = await self.auth_manager.credential_capture(auth_url)
                    await self.auth_manager.flow_handler.present_credential_input(
                        schema, system, connection_id, state, self._run_context
                    )
            except Exception as exc:
                return {
                    "status": "error",
                    "error": f"Access to {system} could not be requested: {exc}",
                    "semantic_error": "CONSENT_NOT_STARTED",
                }
            return {
                "status": "waiting",
                "hitl_required": True,
                "hitl_type": "auth",
                "typed_outcome": "WAITING_FOR_CONSENT",
                "system": system,
                "connection_id": connection_id,
                "workflow_id": self._run_context.get("workflow_id"),
                "step_id": self._run_context.get("step_id"),
                "detail": (
                    f"Waiting for a person to connect {system}. The task will "
                    "resume from this turn after consent completes."
                ),
            }

        return request_access

    def _atom_tool(self, name: str):
        async def call(**params):
            from jarviscore.execution.atom_contract import invocation

            atom = self._atoms.get(name)
            registry = self.code_registry
            code = registry.get_function_code(name) if registry is not None else None
            if atom is None or not code:
                return {
                    "status": "error",
                    "error": f"`{name}` is no longer in the registry.",
                    "semantic_error": "ATOM_UNAVAILABLE",
                }
            action_id = self._atom_action_id(atom, params)
            if atom.policy.requires_approval and action_id not in set(
                self._run_context.get("_approved_actions") or ()
            ):
                return {
                    "status": "waiting",
                    "hitl_required": True,
                    "hitl_type": "approval",
                    "typed_outcome": "WAITING_FOR_APPROVAL",
                    "system": atom.system,
                    "action_id": action_id,
                    "action": atom.describe(),
                    "consequence": atom.policy.consequence,
                    "workflow_id": self._run_context.get("workflow_id"),
                    "step_id": self._run_context.get("step_id"),
                    "detail": f"Waiting for approval before {atom.name} runs.",
                }
            prior = self._idempotent_result(action_id)
            if prior is not None:
                return prior
            # Runs where any other sandbox code runs: nexus_call attaches the
            # credential there, so proving an atom is just running it.
            result = await self._tool_execute_code(
                code=f"{code}\n\n{invocation(atom, params)}",
                description=f"{name} via {atom.system}",
            )
            self._record_atom_outcome(name, result)
            if atom.policy.effect == "destructive" and result.get("status") == "success":
                self._save_idempotent_result(action_id, result)
            return result
        call.__name__ = name
        return call

    @staticmethod
    def _atom_action_id(atom, params: Dict[str, Any]) -> str:
        import hashlib
        import json

        identity = {
            field: params.get(field) for field in atom.policy.idempotency_fields
        }
        encoded = json.dumps(
            {"atom": atom.name, "identity": identity}, sort_keys=True, default=str
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _idempotent_result(self, action_id: str):
        store = self.redis_store
        if store is None or not hasattr(store, "get_atom_execution"):
            return None
        return store.get_atom_execution(action_id)

    def _save_idempotent_result(self, action_id: str, result: Dict[str, Any]) -> None:
        store = self.redis_store
        if store is not None and hasattr(store, "save_atom_execution"):
            store.save_atom_execution(action_id, result)

    def _record_atom_outcome(self, name: str, result: Dict[str, Any]) -> None:
        """An atom called as a tool is the evidence its stage is built on.

        This is the path agents use once a provider is connected, so leaving it
        unrecorded meant the registry never learned from the calls that matter.
        A refusal at the credential boundary is not recorded: the atom never ran.
        """
        if self.code_registry is None:
            return
        status = result.get("status")
        if status not in ("success", "failure") or result.get("access_failure"):
            return
        try:
            self.code_registry.update_execution_stats(
                name,
                success=status == "success",
                execution_time=float(result.get("execution_time") or 0.0),
                error_type=result.get("error_type"),
            )
        except Exception as exc:
            logger.warning("Failed to record outcome for atom %s: %s", name, exc)
