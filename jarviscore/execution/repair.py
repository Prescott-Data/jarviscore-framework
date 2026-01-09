"""
Autonomous Repair - LLM-based automatic code fixing
Analyzes errors and generates corrected code
"""
import ast
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class AutonomousRepair:
    """
    Automatic code repair using LLM.

    Philosophy:
    - Code execution fails → analyze error
    - LLM generates fixed version
    - Validate and retry (max 3 attempts)
    - Learn from previous failures

    Example:
        repair = AutonomousRepair(code_generator)
        fixed_code = await repair.repair(
            original_code="result = 1/0",
            error=ZeroDivisionError("division by zero"),
            task={"task": "Calculate result"}
        )
    """

    def __init__(self, code_generator, max_attempts: int = 3):
        """
        Initialize repair system.

        Args:
            code_generator: CodeGenerator instance
            max_attempts: Maximum repair attempts (default 3)
        """
        self.codegen = code_generator
        self.max_attempts = max_attempts

        self.repair_template = self._load_repair_template()

    def _load_repair_template(self) -> str:
        """Load prompt template for code repair."""
        return """You are an expert Python debugger. The following code FAILED during execution.

ORIGINAL CODE:
```python
{original_code}
```

ERROR DETAILS:
Type: {error_type}
Message: {error_message}

ORIGINAL TASK:
{task}

{previous_attempts}

INSTRUCTIONS:
1. Analyze the error carefully
2. Identify the root cause (syntax error, logic error, missing import, etc.)
3. Generate FIXED Python code that:
   - Solves the original task
   - Handles the error properly
   - Stores result in 'result' variable
   - Is complete and executable

CRITICAL:
- Write ONLY executable Python code (no explanations)
- DO NOT repeat the same mistake
- Add proper error handling (try/except)
- Test edge cases in your mind

Generate the FIXED code now (code only):
"""

    async def repair(
        self,
        code: str,
        error: Exception,
        task: Dict[str, Any],
        system_prompt: str,
        attempt: int = 1,
        previous_attempts: Optional[list] = None
    ) -> str:
        """
        Repair failed code using LLM.

        Args:
            code: Original code that failed
            error: Exception that occurred
            task: Original task specification
            system_prompt: Agent's system prompt
            attempt: Current repair attempt number (1-3)
            previous_attempts: List of previous failed attempts

        Returns:
            Fixed Python code

        Raises:
            RuntimeError: If max attempts exceeded
            ValueError: If fixed code has syntax errors

        Example:
            try:
                result = await executor.execute(code)
            except Exception as e:
                fixed_code = await repair.repair(code, e, task, system_prompt)
                result = await executor.execute(fixed_code)
        """
        if attempt > self.max_attempts:
            raise RuntimeError(
                f"Repair failed after {self.max_attempts} attempts. "
                f"Last error: {error}"
            )

        logger.info(f"Attempting code repair (attempt {attempt}/{self.max_attempts})")
        logger.debug(f"Error: {type(error).__name__}: {error}")

        # Format previous attempts info
        attempts_info = ""
        if previous_attempts:
            attempts_info = "PREVIOUS FAILED ATTEMPTS:\n"
            for i, prev in enumerate(previous_attempts, 1):
                attempts_info += f"\nAttempt {i}:\n"
                attempts_info += f"Error: {prev['error']}\n"
                attempts_info += f"Code:\n```python\n{prev['code']}\n```\n"

        # Build repair prompt
        prompt = self.repair_template.format(
            original_code=code,
            error_type=type(error).__name__,
            error_message=str(error),
            task=task.get('task', ''),
            previous_attempts=attempts_info
        )

        # Add system context
        prompt = f"{system_prompt}\n\n{prompt}"

        try:
            # Generate fixed code via LLM
            response = await self.codegen.llm.generate(
                prompt=prompt,
                temperature=0.4,  # Slightly higher for creative problem solving
                max_tokens=4000
            )

            fixed_code = response['content']

            # Clean up code
            fixed_code = self.codegen._clean_code(fixed_code)

            # Validate syntax
            self._validate_fix(fixed_code)

            logger.info(f"Code repair attempt {attempt} successful")
            return fixed_code

        except Exception as e:
            logger.error(f"Repair attempt {attempt} failed: {e}")
            raise RuntimeError(f"Failed to repair code: {e}")

    def _validate_fix(self, code: str):
        """
        Validate that fixed code has correct syntax.

        Args:
            code: Fixed Python code

        Raises:
            ValueError: If code has syntax errors
        """
        try:
            ast.parse(code)
            logger.debug("Fixed code syntax validation passed")
        except SyntaxError as e:
            logger.error(f"Fixed code still has syntax errors: {e}")
            raise ValueError(f"Repaired code has syntax errors: {e}")

    async def repair_with_retries(
        self,
        code: str,
        error: Exception,
        task: Dict[str, Any],
        system_prompt: str,
        executor
    ) -> Dict[str, Any]:
        """
        Repair code with automatic retry on failure.

        This is a high-level method that:
        1. Attempts repair
        2. Executes fixed code
        3. If still fails, tries again (up to max_attempts)

        Args:
            code: Original failed code
            error: Exception from execution
            task: Task specification
            system_prompt: Agent system prompt
            executor: SandboxExecutor instance for testing fixes

        Returns:
            Final execution result (success or failure)

        Example:
            result = await repair.repair_with_retries(
                code, error, task, system_prompt, executor
            )
        """
        previous_attempts = []
        current_code = code
        current_error = error

        for attempt in range(1, self.max_attempts + 1):
            try:
                # Track this attempt
                previous_attempts.append({
                    'code': current_code,
                    'error': str(current_error)
                })

                # Generate fix
                fixed_code = await self.repair(
                    code=current_code,
                    error=current_error,
                    task=task,
                    system_prompt=system_prompt,
                    attempt=attempt,
                    previous_attempts=previous_attempts if attempt > 1 else None
                )

                # Test the fix
                logger.info(f"Testing repair attempt {attempt}...")
                result = await executor.execute(fixed_code)

                if result['status'] == 'success':
                    logger.info(f"✓ Repair succeeded on attempt {attempt}")
                    return result
                else:
                    # Fix didn't work, prepare for next attempt
                    current_code = fixed_code
                    current_error = Exception(result.get('error', 'Unknown error'))
                    logger.warning(
                        f"Repair attempt {attempt} executed but failed: "
                        f"{result.get('error')}"
                    )

            except Exception as e:
                logger.error(f"Repair attempt {attempt} failed with exception: {e}")
                current_error = e
                if attempt == self.max_attempts:
                    # Last attempt failed
                    return {
                        'status': 'failure',
                        'error': f'All {self.max_attempts} repair attempts exhausted',
                        'last_error': str(e)
                    }

        # Should not reach here, but just in case
        return {
            'status': 'failure',
            'error': f'Repair failed after {self.max_attempts} attempts',
            'attempts': previous_attempts
        }


def create_autonomous_repair(code_generator, max_attempts: int = 3) -> AutonomousRepair:
    """
    Factory function to create autonomous repair system.

    Args:
        code_generator: CodeGenerator instance
        max_attempts: Max repair attempts (default 3)

    Returns:
        AutonomousRepair instance
    """
    return AutonomousRepair(code_generator, max_attempts)
