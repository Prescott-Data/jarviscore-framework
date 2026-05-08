"""
Code Generator - LLM-based Python code generation with REACTPP discipline.

Upgraded from integration-agent staging branch patterns:
- REACTPP 2-block output format (JSON metadata + Python — nothing else)
- Registry pre-check: inject existing capabilities before generation
- HTTP contract enforcement via ValidationLayer
- Self-repair loop for syntax errors and contract violations
- Low temperature (0.2) for deterministic, high-quality code
"""
import ast
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Output Model
# ─────────────────────────────────────────────────────────────────

@dataclass
class GeneratedCode:
    """Structured output from code generation."""
    code: str
    system: Optional[str] = None                  # e.g. "linkedin", "google_analytics"
    oauth_required: bool = False
    provider_name: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    repair_attempts: int = 0
    validation_passed: bool = True


# ─────────────────────────────────────────────────────────────────
# Prompt Templates
# ─────────────────────────────────────────────────────────────────

# REACTPP system prompt — mirrors integration-agent CodeGenerator philosophy.
# Key mandates:
#   1. Identify provider + action from task.
#   2. Use discovered schemas / training knowledge — no hardcoded mappings.
#   3. Structured return: {"success": bool, "data": ..., "error": ...}
#   4. EXACTLY 2 output blocks — JSON metadata then Python code.
_REACTPP_SYSTEM_PROMPT = """\
You are the JarvisCore Execution Agent for enterprise workflows.
You integrate external systems via APIs using disciplined reasoning.

## Mission
Write clean, correct Python code that fulfills the given task.
Store the final result in a variable called `result`.

## Reasoning Principles
1. Identify the provider, action, and target resources from the task.
2. Validate prerequisites before execution (auth tokens, IDs, required fields).
3. Prefer least-privilege scopes and user-context endpoints.
4. Use provider documentation or your training knowledge of the API.
   NEVER hardcode mappings or placeholder values.
5. Return explicit success/error with actionable remediation.

## Authentication
- Auth credentials are provided via STEP_DATA["auth"] or environment variables.
- NEVER hardcode tokens, API keys, or passwords in generated code.
- Include auth headers for all external API calls.
- If auth is missing, return {"success": False, "error": "Auth required: <provider>"}

## Code Quality
- Include ONLY required imports at the top.
- Validate inputs early and fail fast.
- Use structured return: {"success": bool, "data": ..., "error": ..., "reactpp_steps": [...]}
- Add response.raise_for_status() after every HTTP call.
- Log meaningful steps at INFO level.

## Using Existing Capabilities
If EXISTING CAPABILITIES are listed below, DO NOT reinvent them.
Reference them directly — assume a module-level object is available.

## Output Format — EXACTLY 2 blocks, no prose outside them

Block 1: JSON metadata
```json
{"oauth_required": true|false, "provider_name": "...", "scopes": ["..."]}
```

Block 2: Python implementation
```python
...code...
```
"""

# Repair prompt — separate from generation to keep context clean.
# The LLM sees the broken code + error + traceback. Nothing else.
_REPAIR_PROMPT_TEMPLATE = """\
You are in autonomous repair mode.
A previously generated function failed. Fix it.

## Failed Code
```python
{code}
```

## Error
{error}

## Requirements
- Same function signature
- Fix ONLY the identified error
- Keep all required imports
- Return dict with 'success' key
- No explanations — only a ```python ... ``` block
"""


# ─────────────────────────────────────────────────────────────────
# Code Generator
# ─────────────────────────────────────────────────────────────────

class CodeGenerator:
    """
    Production-grade code generator.

    Pipeline:
        generate(task, registry) →
            1. registry_snapshot = registry.check_existing_capabilities(system)
            2. prompt = REACTPP_SYSTEM_PROMPT + existing_caps + task
            3. LLM response → extract JSON metadata + Python code
            4. ast.parse check → repair if broken
            5. ValidationLayer.validate_pre_execution → repair if violated
            6. Return GeneratedCode(code, oauth_metadata)

    Example:
        gen = CodeGenerator(llm_client)
        result = await gen.generate(
            task={"task": "Post article to LinkedIn", "auth": {"access_token": "..."}},
            system="linkedin"
        )
        print(result.code)
    """

    def __init__(self, llm_client, search_client=None):
        self.llm = llm_client
        self.search = search_client

        # Import validation layer (lazy to avoid circular imports)
        self._validation_layer = None

    def _get_validation_layer(self):
        if self._validation_layer is None:
            from jarviscore.execution.validation import ValidationLayer
            self._validation_layer = ValidationLayer()
        return self._validation_layer

    # ─────────────────────────────────────────────────────────────
    # Main Entry Point
    # ─────────────────────────────────────────────────────────────

    async def generate(
        self,
        task: Dict[str, Any],
        system: Optional[str] = None,
        registry=None,
        context: Optional[Dict] = None,
        max_repair_attempts: int = 2,
    ) -> GeneratedCode:
        """
        Generate Python code for a task.

        Args:
            task: Task dict with 'task' key (natural language description).
            system: System/provider name (e.g. "linkedin", "google_analytics").
                    Used to look up existing capabilities in the registry.
            registry: Optional FunctionRegistry — checked before generation.
            context: Optional context from prior steps (e.g. previous outputs).
            max_repair_attempts: Max LLM repair cycles on validation failure.

        Returns:
            GeneratedCode with validated, executable Python code.

        Raises:
            RuntimeError: If generation + all repair attempts fail.
        """
        task_description = task.get("task", "") or str(task)
        logger.info("CodeGenerator: generating for — %s", task_description[:100])

        # 1. Build existing capabilities snippet from registry
        existing_caps_snippet = ""
        if registry and system:
            existing_caps_snippet = self._build_existing_caps_snippet(registry, system)

        # 2. Build full prompt
        prompt = self._build_prompt(task_description, context, existing_caps_snippet)

        # 3. LLM generation
        raw_response = await self._call_llm(prompt, temperature=0.2)
        if not raw_response:
            raise RuntimeError("LLM returned empty response during code generation.")

        # 4. Extract JSON metadata + Python code from 2-block format
        oauth_meta = self._extract_json_metadata(raw_response)
        code = self._extract_python_code(raw_response)

        if not code:
            raise RuntimeError(
                "LLM did not produce a ```python ... ``` block. "
                f"Raw response:\n{raw_response[:400]}"
            )

        # 5. Validate + repair loop
        code, repair_attempts = await self._validate_and_repair(
            code=code,
            task_description=task_description,
            max_attempts=max_repair_attempts,
        )

        result = GeneratedCode(
            code=code,
            system=system,
            oauth_required=oauth_meta.get("oauth_required", False),
            provider_name=oauth_meta.get("provider_name"),
            scopes=oauth_meta.get("scopes", []),
            repair_attempts=repair_attempts,
            validation_passed=True,
        )

        logger.info(
            "CodeGenerator: done (repairs=%d, oauth=%s)",
            repair_attempts, result.oauth_required,
        )
        return result

    # ─────────────────────────────────────────────────────────────
    # Repair via LLM
    # ─────────────────────────────────────────────────────────────

    async def fix_code(self, code: str, error: str) -> Optional[str]:
        """
        Use LLM to fix a code error.

        This is the autonomous repair mode — uses a dedicated repair prompt,
        not the generation prompt. The LLM only sees broken code + error.

        Args:
            code: Broken source code.
            error: Error message or contract violation description.

        Returns:
            Fixed code string, or None if repair failed.
        """
        logger.info("CodeGenerator.fix_code: repairing — %s", error[:120])
        prompt = _REPAIR_PROMPT_TEMPLATE.format(code=code, error=error)

        try:
            response = await self._call_llm(prompt, temperature=0.3)
            if not response:
                return None
            fixed = self._extract_python_code(response)
            if not fixed:
                # Fallback: try taking the whole response as code
                fixed = self._clean_code(response)
            return fixed or None
        except Exception as exc:
            logger.warning("CodeGenerator.fix_code: LLM repair failed — %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────
    # Validate + Repair Loop
    # ─────────────────────────────────────────────────────────────

    async def _validate_and_repair(
        self,
        code: str,
        task_description: str,
        max_attempts: int,
    ) -> Tuple[str, int]:
        """
        Run ValidationLayer. If invalid, repair via LLM and re-validate.

        Returns (final_code, repair_count).
        Raises RuntimeError if all attempts exhausted.
        """
        validator = self._get_validation_layer()
        repairs = 0

        for attempt in range(max_attempts + 1):
            # Syntax check first
            try:
                ast.parse(code)
            except SyntaxError as e:
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"Code still has syntax errors after {max_attempts} repair(s): {e}"
                    )
                logger.warning("CodeGenerator: SyntaxError on attempt %d — repairing", attempt)
                fixed = await self.fix_code(code, f"SyntaxError at line {e.lineno}: {e.msg}")
                if fixed:
                    code = fixed
                    repairs += 1
                continue

            # Full ValidationLayer check
            vresult = validator.validate_pre_execution(code)
            if vresult.is_valid:
                return code, repairs

            if attempt >= max_attempts:
                raise RuntimeError(
                    f"Code failed validation after {max_attempts} repair(s): {vresult.summary()}"
                )

            logger.warning(
                "CodeGenerator: validation failed on attempt %d — %s. Repairing.",
                attempt, vresult.summary(),
            )
            fixed = await self.fix_code(code, vresult.summary())
            if fixed:
                code = fixed
                repairs += 1
            else:
                raise RuntimeError(
                    f"LLM repair returned None on attempt {attempt + 1}. "
                    f"Validation error: {vresult.summary()}"
                )

        # Should be unreachable
        return code, repairs

    # ─────────────────────────────────────────────────────────────
    # Prompt Construction
    # ─────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        task_description: str,
        context: Optional[Dict],
        existing_caps_snippet: str,
    ) -> str:
        parts = [_REACTPP_SYSTEM_PROMPT]

        if existing_caps_snippet:
            parts.append(f"\n## EXISTING CAPABILITIES\n{existing_caps_snippet}\n")

        if context:
            parts.append(f"\n## CONTEXT FROM PRIOR STEPS\n{self._format_context(context)}\n")

        parts.append(f"\n## TASK\n{task_description}\n")
        parts.append("\nGenerate the 2 required blocks now (JSON metadata then Python code):")

        return "\n".join(parts)

    def _build_existing_caps_snippet(self, registry, system: str) -> str:
        """
        Query registry for existing capabilities and format as prompt snippet.
        Mirrors integration-agent CodeGenerator.check_existing_capabilities().
        """
        try:
            functions = registry.get_functions_by_system(system)
            if not functions:
                return ""

            # Filter to verified/golden only
            production_fns = [
                f for f in functions
                if f.get("registry_stage") in ("verified", "golden")
            ]
            if not production_fns:
                return ""

            cap_names = sorted({
                cap for f in production_fns
                for cap in f.get("capabilities", [])
            })

            fn_names = [f["function_name"] for f in production_fns[:10]]
            more = len(production_fns) - 10 if len(production_fns) > 10 else 0

            system_class = f"{system.title().replace('_', '')}Capabilities"
            lines = [
                f"The following `{system_class}` functions are already in the registry:",
                f"- Capabilities: {', '.join(cap_names) if cap_names else 'N/A'}",
                f"- Functions: {', '.join(fn_names)}" + (f" (+{more} more)" if more else ""),
                f"When generating code, reuse these instead of re-implementing.",
                f"A `{system_class}` object is already available — call its methods directly.",
            ]
            return "\n".join(lines)

        except Exception as exc:
            logger.debug("CodeGenerator: registry capability check failed — %s", exc)
            return ""

    # ─────────────────────────────────────────────────────────────
    # LLM Client
    # ─────────────────────────────────────────────────────────────

    async def _call_llm(self, prompt: str, temperature: float = 0.2) -> Optional[str]:
        """Call the LLM and return the response content string."""
        try:
            response = await self.llm.generate(
                prompt=prompt,
                temperature=temperature,
                max_tokens=4000,
            )
            if isinstance(response, dict):
                return response.get("content") or response.get("text")
            return str(response) if response else None
        except Exception as exc:
            logger.error("CodeGenerator: LLM call failed — %s", exc)
            raise RuntimeError(f"LLM call failed: {exc}") from exc

    # ─────────────────────────────────────────────────────────────
    # Extraction Helpers
    # ─────────────────────────────────────────────────────────────

    def _extract_json_metadata(self, text: str) -> Dict[str, Any]:
        """
        Extract the first ```json ... ``` block from LLM output.

        Returns parsed dict or empty dict if not found.
        """
        match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError as e:
                logger.debug("CodeGenerator: JSON metadata parse error — %s", e)
        # Fallback: look for inline JSON object
        inline = re.search(r'\{"oauth_required".*?\}', text)
        if inline:
            try:
                return json.loads(inline.group(0))
            except json.JSONDecodeError:
                pass
        return {}

    def _extract_python_code(self, text: str) -> Optional[str]:
        """
        Extract the last ```python ... ``` block from LLM output.

        Uses the LAST block because the LLM sometimes emits partial examples
        before the final implementation.
        """
        blocks = re.findall(r"```python\s*\n(.*?)\n```", text, re.DOTALL)
        if blocks:
            candidate = blocks[-1].strip()
            # Quick syntax check — if valid, return as-is
            try:
                ast.parse(candidate)
                return candidate
            except SyntaxError:
                # Try each block from last to first
                for block in reversed(blocks[:-1]):
                    try:
                        ast.parse(block.strip())
                        return block.strip()
                    except SyntaxError:
                        continue
                # Return last block anyway — syntax repair will fix it
                return candidate

        # Fallback: try generic code block
        generic = re.findall(r"```\n(.*?)\n```", text, re.DOTALL)
        if generic:
            return self._clean_code(generic[-1])

        return None

    def _clean_code(self, code: str) -> str:
        """Strip markdown fences and trailing whitespace."""
        code = re.sub(r"^```(?:python)?\s*\n?", "", code, flags=re.MULTILINE)
        code = re.sub(r"\n?```\s*$", "", code, flags=re.MULTILINE)
        return code.strip()

    def _format_context(self, context: Dict) -> str:
        parts = []
        for key, value in context.items():
            if isinstance(value, dict):
                parts.append(f"{key}: {json.dumps(value, default=str)[:500]}")
            else:
                parts.append(f"{key}: {str(value)[:500]}")
        return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────

def create_code_generator(llm_client, search_client=None) -> CodeGenerator:
    """
    Factory function to create a production-grade CodeGenerator.

    Args:
        llm_client: UnifiedLLMClient instance.
        search_client: Optional search client (injected into sandbox if provided).

    Returns:
        CodeGenerator instance.
    """
    return CodeGenerator(llm_client, search_client)
