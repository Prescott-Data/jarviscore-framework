"""
Code Generator - LLM-based Python code generation from natural language
Auto-injects internet search capabilities when needed
"""
import ast
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class CodeGenerator:
    """
    Zero-config code generator using LLM.

    Philosophy:
    - Developer writes natural language task
    - Framework generates executable Python code
    - Auto-injects search tools if task needs web data
    - Validates syntax before returning

    Example:
        gen = CodeGenerator(llm_client, search_client)
        code = await gen.generate(
            task="Search for Python tutorials and count results",
            system_prompt="You are a Python expert"
        )
    """

    def __init__(self, llm_client, search_client=None):
        """
        Initialize code generator.

        Args:
            llm_client: UnifiedLLMClient instance
            search_client: Optional InternetSearch instance (auto-injects if provided)
        """
        self.llm = llm_client
        self.search = search_client

        # Prompt templates
        self.base_template = self._load_base_template()
        self.search_template = self._load_search_template()

    def _load_base_template(self) -> str:
        """Base prompt template for code generation."""
        return """You are an expert Python programmer. Generate clean, working Python code to accomplish the given task.

CRITICAL REQUIREMENTS:
1. Write ONLY executable Python code (no explanations, markdown, or comments outside code)
2. Store the final result in a variable named 'result'
3. Use standard libraries when possible (requests, json, re, etc.)
4. Handle errors gracefully with try/except
5. Do NOT use input() or any blocking operations
6. Do NOT print anything unless explicitly requested
7. Make the code self-contained and complete

AVAILABLE TOOLS:
- Standard library: os, sys, json, re, datetime, math, random, etc.
- HTTP requests: import requests
- Data processing: import pandas (if installed)
- Any pip-installable package (assume it's available)

TASK:
{task}

AGENT CONTEXT:
{system_prompt}

Generate the Python code now (code only, no explanations):
"""

    def _load_search_template(self) -> str:
        """Template when internet search is available."""
        return """You are an expert Python programmer with internet search capabilities. Generate clean, working Python code to accomplish the given task.

CRITICAL REQUIREMENTS:
1. Write ONLY executable Python code (no explanations, markdown, or comments outside code)
2. Store the final result in a variable named 'result'
3. Use standard libraries when possible
4. Handle errors gracefully with try/except
5. Do NOT use input() or any blocking operations
6. Do NOT print anything unless explicitly requested

INTERNET SEARCH AVAILABLE:
You have access to a 'search' object with these async methods:
- await search.search(query, max_results=5) -> List[Dict] with 'title', 'snippet', 'url'
- await search.extract_content(url, max_length=10000) -> Dict with 'title', 'content', 'success'
- await search.search_and_extract(query, num_results=3) -> List[Dict] combined results

Example using search (define async main, sandbox will execute it):
```python
async def main():
    # Search the web
    results = await search.search("Python async tutorial")

    # Extract content from first result
    if results:
        content = await search.extract_content(results[0]['url'])

        # Process and return result
        result = {{
            'title': content['title'],
            'summary': content['content'][:500]
        }}
        return result
    return None
```

IMPORTANT:
- Define async def main() - the sandbox will call it automatically
- Do NOT use asyncio.run() - you're already in an async context
- Store final result by returning from main() or assigning to 'result' variable

TASK:
{task}

AGENT CONTEXT:
{system_prompt}

Generate the Python code now (code only, no explanations):
"""

    async def generate(
        self,
        task: Dict[str, Any],
        system_prompt: str,
        context: Optional[Dict] = None,
        enable_search: bool = True
    ) -> str:
        """
        Generate Python code for a task.

        Args:
            task: Task dict with 'task' key (natural language description)
            system_prompt: Agent's system prompt (role/expertise)
            context: Optional context (dependencies, previous results)
            enable_search: Auto-inject search tools if available (default True)

        Returns:
            Generated Python code as string

        Raises:
            ValueError: If generated code has syntax errors
            RuntimeError: If LLM generation fails

        Example:
            code = await gen.generate(
                task={"task": "Calculate factorial of 10"},
                system_prompt="You are a math expert"
            )
        """
        task_description = task.get('task', '')
        logger.info(f"Generating code for: {task_description[:80]}...")

        # Decide whether to inject search tools
        use_search = enable_search and self.search is not None
        if use_search:
            logger.debug("Search tools available - using search template")
            template = self.search_template
        else:
            template = self.base_template

        # Build prompt
        prompt = template.format(
            task=task_description,
            system_prompt=system_prompt
        )

        # Add context if provided
        if context:
            prompt += f"\n\nCONTEXT FROM PREVIOUS STEPS:\n{self._format_context(context)}\n"

        # Generate code via LLM
        try:
            response = await self.llm.generate(
                prompt=prompt,
                temperature=0.3,  # Lower temp for code generation
                max_tokens=4000
            )

            code = response['content']
            logger.debug(f"Generated {len(code)} chars of code")

            # Clean up code (remove markdown blocks if present)
            code = self._clean_code(code)

            # Validate syntax
            self._validate_code(code)

            logger.info("Code generation successful")
            return code

        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            raise RuntimeError(f"Failed to generate code: {e}")

    def _clean_code(self, code: str) -> str:
        """
        Clean up generated code (remove markdown, explanations).

        Args:
            code: Raw LLM output

        Returns:
            Clean Python code
        """
        # Remove markdown code blocks
        import re

        # Pattern: ```python ... ``` or ```...```
        pattern = r'```(?:python)?\s*\n(.*?)\n```'
        matches = re.findall(pattern, code, re.DOTALL)

        if matches:
            # Use the first code block found
            code = matches[0]

        # Remove leading/trailing whitespace
        code = code.strip()

        # Remove any lines that are just comments at the start
        lines = code.split('\n')
        while lines and lines[0].strip().startswith('#'):
            lines.pop(0)

        code = '\n'.join(lines)

        return code

    def _validate_code(self, code: str):
        """
        Validate Python syntax.

        Args:
            code: Python code string

        Raises:
            ValueError: If code has syntax errors
        """
        try:
            ast.parse(code)
            logger.debug("Code syntax validation passed")
        except SyntaxError as e:
            logger.error(f"Syntax error in generated code: {e}")
            logger.error(f"Problematic code:\n{code}")
            raise ValueError(f"Generated code has syntax errors: {e}")

    def _format_context(self, context: Dict) -> str:
        """Format context from previous steps for prompt."""
        parts = []
        for key, value in context.items():
            parts.append(f"{key}: {value}")
        return "\n".join(parts)


def create_code_generator(llm_client, search_client=None) -> CodeGenerator:
    """
    Factory function to create code generator.

    Args:
        llm_client: LLM client instance
        search_client: Optional search client (auto-injected if provided)

    Returns:
        CodeGenerator instance
    """
    return CodeGenerator(llm_client, search_client)
