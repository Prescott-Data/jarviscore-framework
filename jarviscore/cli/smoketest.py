"""
JarvisCore Smoke Test CLI

Quick validation that AutoAgent/Prompt-Dev workflow works end-to-end.
Tests: LLM → Code Generation → Sandbox Execution → Result

Usage:
    python -m jarviscore.cli.smoketest              # Run basic smoke test
    python -m jarviscore.cli.smoketest --verbose    # Show detailed output
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime


class SmokeTest:
    """Smoke test runner for JarvisCore AutoAgent."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.passed = []
        self.failed = []
        self.start_time = None
        self.end_time = None

    def print_header(self):
        """Print test header."""
        print("\n" + "="*70)
        print("  JarvisCore Smoke Test")
        print("  Validating AutoAgent: Prompt → Code → Result")
        print("="*70 + "\n")

    def print_test(self, name: str, status: bool, detail: str = "", duration: float = None):
        """Print test result."""
        symbol = "✓" if status else "✗"
        duration_str = f" ({duration:.2f}s)" if duration else ""

        print(f"{symbol} {name}{duration_str}")

        if self.verbose or not status:
            if detail:
                for line in detail.split('\n'):
                    print(f"  {line}")

        if status:
            self.passed.append(name)
        else:
            self.failed.append((name, detail))

    async def test_imports(self) -> bool:
        """Test that core framework modules load."""
        test_start = asyncio.get_event_loop().time()

        try:
            from jarviscore import Mesh
            from jarviscore.profiles import AutoAgent
            from dotenv import load_dotenv

            duration = asyncio.get_event_loop().time() - test_start
            self.print_test("Import Framework", True, "Core modules loaded", duration)
            return True

        except Exception as e:
            duration = asyncio.get_event_loop().time() - test_start
            self.print_test("Import Framework", False, str(e), duration)
            return False

    async def test_env_config(self) -> bool:
        """Test environment configuration."""
        test_start = asyncio.get_event_loop().time()

        try:
            import os
            from dotenv import load_dotenv

            # Load .env
            env_paths = [Path.cwd() / '.env', Path.cwd() / 'jarviscore' / '.env']
            env_loaded = False

            for env_path in env_paths:
                if env_path.exists():
                    load_dotenv(env_path)
                    env_loaded = True
                    break

            # Check for at least one LLM configured
            llm_providers = {
                'CLAUDE_API_KEY': os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY'),
                'AZURE_API_KEY': os.getenv('AZURE_API_KEY') or os.getenv('AZURE_OPENAI_KEY'),
                'GEMINI_API_KEY': os.getenv('GEMINI_API_KEY'),
                'LLM_ENDPOINT': os.getenv('LLM_ENDPOINT'),
            }

            configured = [k for k, v in llm_providers.items() if v]

            if not configured:
                duration = asyncio.get_event_loop().time() - test_start
                self.print_test(
                    "Configuration",
                    False,
                    "No LLM provider configured. Add API key to .env file.",
                    duration
                )
                return False

            duration = asyncio.get_event_loop().time() - test_start
            provider_str = configured[0].replace('_', ' ').title()
            self.print_test("Configuration", True, f"Using {provider_str}", duration)
            return True

        except Exception as e:
            duration = asyncio.get_event_loop().time() - test_start
            self.print_test("Configuration", False, str(e), duration)
            return False

    async def test_mesh_creation(self) -> bool:
        """Test mesh creation."""
        test_start = asyncio.get_event_loop().time()

        try:
            from jarviscore import Mesh

            mesh = Mesh(mode="autonomous")

            duration = asyncio.get_event_loop().time() - test_start
            self.print_test("Create Mesh", True, "Autonomous mode initialized", duration)
            return True

        except Exception as e:
            duration = asyncio.get_event_loop().time() - test_start
            self.print_test("Create Mesh", False, str(e), duration)
            return False

    async def test_agent_definition(self) -> bool:
        """Test agent definition."""
        test_start = asyncio.get_event_loop().time()

        try:
            from jarviscore.profiles import AutoAgent

            class TestAgent(AutoAgent):
                role = "calculator"
                capabilities = ["math", "calculation"]
                system_prompt = "You are a math expert. Generate Python code to solve problems."

            agent = TestAgent()

            duration = asyncio.get_event_loop().time() - test_start
            self.print_test("Define Agent", True, "AutoAgent class created", duration)
            return True

        except Exception as e:
            duration = asyncio.get_event_loop().time() - test_start
            self.print_test("Define Agent", False, str(e), duration)
            return False

    async def test_end_to_end_execution(self) -> bool:
        """Test full workflow: prompt → code → result."""
        test_start = asyncio.get_event_loop().time()

        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                from jarviscore import Mesh
                from jarviscore.profiles import AutoAgent

                # Define agent
                class CalculatorAgent(AutoAgent):
                    role = "calculator"
                    capabilities = ["math"]
                    system_prompt = "You are a math expert. Generate Python code. Store result in 'result' variable."

                # Create mesh and add agent
                mesh = Mesh(mode="autonomous")
                mesh.add(CalculatorAgent)

                # Start mesh
                await mesh.start()

                if self.verbose and attempt > 0:
                    print(f"  Retry attempt {attempt + 1}/{max_retries}...")

                # Execute simple task
                task_start = asyncio.get_event_loop().time()
                results = await mesh.workflow("smoke-test", [
                    {
                        "agent": "calculator",
                        "task": "Calculate 2 + 2"
                    }
                ])

                task_duration = asyncio.get_event_loop().time() - task_start

                # Validate result
                result = results[0]

                # Check for success (status can be 'success' or 'completed')
                if result.get('status') not in ['success', 'completed']:
                    error_msg = result.get('error', 'Unknown error')

                    # Check if it's a retryable error (rate limit, overloaded, timeout)
                    if any(x in str(error_msg).lower() for x in ['overloaded', '529', 'rate limit', 'timeout']):
                        if attempt < max_retries - 1:
                            if self.verbose:
                                print(f"  LLM temporarily unavailable, retrying in {retry_delay}s...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            await mesh.stop()
                            continue

                    raise Exception(f"Task failed: {error_msg}")

                output = result.get('output')
                if output != 4:
                    raise Exception(f"Expected 4, got {output}")

                # Stop mesh
                await mesh.stop()

                duration = asyncio.get_event_loop().time() - test_start

                detail = f"Task: '2 + 2' → Result: {output}\n"
                detail += f"Execution time: {task_duration:.2f}s\n"
                detail += f"Repairs: {result.get('repairs', 0)}"
                if attempt > 0:
                    detail += f"\nRetries: {attempt}"

                self.print_test("End-to-End Workflow", True, detail, duration)
                return True

            except Exception as e:
                # Check if this is the last attempt
                if attempt == max_retries - 1:
                    duration = asyncio.get_event_loop().time() - test_start

                    error_detail = str(e)
                    if self.verbose:
                        import traceback
                        error_detail = traceback.format_exc()

                    self.print_test("End-to-End Workflow", False, error_detail, duration)
                    return False

                # Otherwise, retry if it's a retryable error
                error_str = str(e).lower()
                if any(x in error_str for x in ['overloaded', '529', 'rate limit', 'timeout']):
                    if self.verbose:
                        print(f"  LLM temporarily unavailable (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue

                # Non-retryable error, fail immediately
                duration = asyncio.get_event_loop().time() - test_start
                error_detail = str(e)
                if self.verbose:
                    import traceback
                    error_detail = traceback.format_exc()
                self.print_test("End-to-End Workflow", False, error_detail, duration)
                return False

        return False

    def print_summary(self):
        """Print test summary."""
        print("\n" + "="*70)
        print("  Summary")
        print("="*70 + "\n")

        total = len(self.passed) + len(self.failed)
        duration = self.end_time - self.start_time if self.start_time and self.end_time else 0

        print(f"Tests run:  {total}")
        print(f"Passed:     {len(self.passed)} ✓")
        print(f"Failed:     {len(self.failed)} ✗")
        print(f"Duration:   {duration:.2f}s")

        if self.failed:
            print("\n" + "="*70)
            print("  Failed Tests")
            print("="*70 + "\n")

            for name, detail in self.failed:
                print(f"✗ {name}")
                if detail:
                    print(f"  {detail}\n")

            print("\n" + "="*70)
            print("  Troubleshooting")
            print("="*70)

            if any("No LLM provider" in detail for _, detail in self.failed):
                print("\nNo LLM configured:")
                print("  1. Copy .env.example to .env")
                print("  2. Add your API key (CLAUDE_API_KEY, AZURE_API_KEY, or GEMINI_API_KEY)")
                print("  3. Run health check: python -m jarviscore.cli.check --validate-llm")

            if any("Task failed" in detail or "error" in detail.lower() for _, detail in self.failed):
                print("\nExecution failed:")
                print("  1. Check LLM API key is valid")
                print("  2. Test connectivity: python -m jarviscore.cli.check --validate-llm")
                print("  3. Check logs: ls -la logs/")
                print("  4. Run with verbose: python -m jarviscore.cli.smoketest --verbose")

            print()
            return False

        print("\n✓ All smoke tests passed!")
        print("\nJarvisCore is working correctly. Next steps:")
        print("  1. Try examples: python examples/calculator_agent_example.py")
        print("  2. Read user guide: docs/USER_GUIDE.md")
        print("  3. Build your first agent: docs/GETTING_STARTED.md")
        print()
        return True

    async def run(self) -> bool:
        """Run all smoke tests."""
        self.print_header()
        self.start_time = asyncio.get_event_loop().time()

        print("[Framework Tests]")
        imports_ok = await self.test_imports()
        if not imports_ok:
            self.end_time = asyncio.get_event_loop().time()
            self.print_summary()
            return False

        config_ok = await self.test_env_config()
        if not config_ok:
            self.end_time = asyncio.get_event_loop().time()
            self.print_summary()
            return False

        mesh_ok = await self.test_mesh_creation()
        agent_ok = await self.test_agent_definition()

        print("\n[Integration Test]")
        e2e_ok = await self.test_end_to_end_execution()

        self.end_time = asyncio.get_event_loop().time()

        return self.print_summary()


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='JarvisCore Smoke Test - Quick validation'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed output and stack traces'
    )

    args = parser.parse_args()

    smoke_test = SmokeTest(verbose=args.verbose)
    success = asyncio.run(smoke_test.run())

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
