"""
JarvisCore Health Check CLI

Validates installation, configuration, and LLM connectivity.

Usage:
    python -m jarviscore.cli.check                 # Basic health check
    python -m jarviscore.cli.check --validate-llm  # Test LLM connectivity
    python -m jarviscore.cli.check --verbose       # Show detailed info
"""

import sys
import os
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple
import importlib.util


class HealthChecker:
    """Health check orchestrator for JarvisCore setup."""

    def __init__(self, validate_llm: bool = False, verbose: bool = False):
        self.validate_llm = validate_llm
        self.verbose = verbose
        self.issues: List[str] = []
        self.warnings: List[str] = []
        self.successes: List[str] = []

    def print_header(self):
        """Print check header."""
        print("\n" + "="*70)
        print("  JarvisCore Health Check")
        print("  Testing AutoAgent/Prompt-Dev Profile")
        print("="*70 + "\n")

    def check_python_version(self) -> bool:
        """Check Python version >= 3.10."""
        version = sys.version_info
        status = version >= (3, 10)

        if status:
            self.successes.append(f"Python {version.major}.{version.minor}.{version.micro}")
        else:
            self.issues.append(
                f"Python {version.major}.{version.minor} found, but 3.10+ required"
            )

        self._print_status("Python Version", status,
                          f"{version.major}.{version.minor}.{version.micro}")
        return status

    def check_jarviscore_installed(self) -> bool:
        """Check if jarviscore package is installed."""
        try:
            import jarviscore
            version = getattr(jarviscore, '__version__', '0.1.0')
            self.successes.append(f"JarvisCore {version} installed")
            self._print_status("JarvisCore Package", True, f"v{version}")
            return True
        except ImportError as e:
            self.issues.append(f"JarvisCore not installed: {e}")
            self._print_status("JarvisCore Package", False, "Not found")
            return False

    def check_dependencies(self) -> Dict[str, bool]:
        """Check core dependencies."""
        deps = {
            'pydantic': 'Core validation',
            'pydantic_settings': 'Configuration management',
        }

        results = {}
        print("\n[Dependencies]")

        for dep, description in deps.items():
            try:
                spec = importlib.util.find_spec(dep)
                installed = spec is not None
                results[dep] = installed

                if installed:
                    self.successes.append(f"{dep}: {description}")
                else:
                    self.issues.append(f"{dep} not installed: {description}")

                self._print_status(f"  {dep}", installed, description)
            except Exception as e:
                results[dep] = False
                self.issues.append(f"{dep} check failed: {e}")
                self._print_status(f"  {dep}", False, str(e))

        return results

    def check_env_file(self) -> Tuple[bool, Path]:
        """Check if .env file exists."""
        env_paths = [
            Path.cwd() / '.env',
            Path.cwd() / 'jarviscore' / '.env',
        ]

        for env_path in env_paths:
            if env_path.exists():
                self.successes.append(f".env found at {env_path}")
                self._print_status(".env File", True, str(env_path))
                return True, env_path

        self.warnings.append(".env file not found - using environment variables")
        self._print_status(".env File", False, "Not found (will use environment vars)")
        return False, None

    def check_llm_config(self) -> Dict[str, bool]:
        """Check which LLM providers are configured."""
        providers = {
            'Claude': ['CLAUDE_API_KEY', 'ANTHROPIC_API_KEY'],
            'Azure OpenAI': ['AZURE_API_KEY', 'AZURE_OPENAI_KEY'],
            'Gemini': ['GEMINI_API_KEY'],
            'vLLM': ['LLM_ENDPOINT'],
        }

        configured = {}
        print("\n[LLM Configuration]")

        for provider, env_vars in providers.items():
            is_configured = any(os.getenv(var) for var in env_vars)
            configured[provider] = is_configured

            if is_configured:
                key_name = next(var for var in env_vars if os.getenv(var))
                masked = self._mask_api_key(os.getenv(key_name))
                self.successes.append(f"{provider} configured")
                self._print_status(f"  {provider}", True, f"{key_name}={masked}")
            else:
                self._print_status(f"  {provider}", False, "Not configured")

        if not any(configured.values()):
            self.issues.append(
                "No LLM provider configured. AutoAgent requires at least one LLM."
            )

        return configured

    async def validate_llm_connectivity(self, configured: Dict[str, bool]):
        """Test actual LLM connectivity."""
        print("\n[LLM Connectivity Test]")

        # Load environment
        from dotenv import load_dotenv
        load_dotenv()

        # Try each configured provider
        for provider, is_configured in configured.items():
            if not is_configured:
                continue

            try:
                if provider == "Claude":
                    success = await self._test_claude()
                elif provider == "Azure OpenAI":
                    success = await self._test_azure()
                elif provider == "Gemini":
                    success = await self._test_gemini()
                elif provider == "vLLM":
                    success = await self._test_vllm()
                else:
                    continue

                if success:
                    self.successes.append(f"{provider} connectivity OK")
                    self._print_status(f"  {provider} API", True, "Connected")
                else:
                    self.issues.append(f"{provider} connection failed")
                    self._print_status(f"  {provider} API", False, "Connection failed")

            except Exception as e:
                self.issues.append(f"{provider} test failed: {str(e)}")
                self._print_status(f"  {provider} API", False, str(e))

    async def _test_claude(self) -> bool:
        """Test Claude API connectivity."""
        try:
            from anthropic import AsyncAnthropic

            api_key = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                return False

            client = AsyncAnthropic(api_key=api_key)

            # Simple test message
            response = await client.messages.create(
                model=os.getenv('CLAUDE_MODEL', 'claude-sonnet-4'),
                max_tokens=10,
                messages=[{"role": "user", "content": "Reply with just 'OK'"}]
            )

            return response.content[0].text.strip().upper() == 'OK'

        except Exception:
            return False

    async def _test_azure(self) -> bool:
        """Test Azure OpenAI connectivity."""
        try:
            from openai import AsyncAzureOpenAI

            client = AsyncAzureOpenAI(
                api_key=os.getenv('AZURE_API_KEY') or os.getenv('AZURE_OPENAI_KEY'),
                api_version=os.getenv('AZURE_API_VERSION', '2024-02-15-preview'),
                azure_endpoint=os.getenv('AZURE_ENDPOINT')
            )

            response = await client.chat.completions.create(
                model=os.getenv('AZURE_DEPLOYMENT', 'gpt-4o'),
                messages=[{"role": "user", "content": "Reply with just 'OK'"}],
                max_tokens=10
            )

            return response.choices[0].message.content.strip().upper() == 'OK'

        except Exception:
            return False

    async def _test_gemini(self) -> bool:
        """Test Gemini connectivity."""
        try:
            import google.generativeai as genai

            genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
            model = genai.GenerativeModel(os.getenv('GEMINI_MODEL', 'gemini-1.5-flash'))

            response = await model.generate_content_async("Reply with just 'OK'")
            return 'OK' in response.text.upper()

        except Exception:
            return False

    async def _test_vllm(self) -> bool:
        """Test vLLM endpoint connectivity."""
        try:
            import httpx

            endpoint = os.getenv('LLM_ENDPOINT')
            if not endpoint:
                return False

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{endpoint}/health")
                return response.status_code == 200

        except Exception:
            return False

    def check_sandbox_config(self):
        """Check sandbox configuration."""
        print("\n[Sandbox Configuration]")

        mode = os.getenv('SANDBOX_MODE', 'local')
        self._print_status("  Sandbox Mode", True, mode)

        if mode == 'remote':
            service_url = os.getenv('SANDBOX_SERVICE_URL')
            if service_url:
                self.successes.append(f"Remote sandbox: {service_url}")
                self._print_status("  Remote Service", True, service_url)
            else:
                self.warnings.append("SANDBOX_MODE=remote but no SANDBOX_SERVICE_URL set")
                self._print_status("  Remote Service", False, "URL not set")

    def print_summary(self):
        """Print summary and recommendations."""
        print("\n" + "="*70)
        print("  Summary")
        print("="*70 + "\n")

        total_checks = len(self.successes) + len(self.issues) + len(self.warnings)

        if self.successes:
            print(f"✓ {len(self.successes)} checks passed")

        if self.warnings:
            print(f"⚠ {len(self.warnings)} warnings")
            for warning in self.warnings:
                print(f"  - {warning}")

        if self.issues:
            print(f"\n✗ {len(self.issues)} issues found:")
            for issue in self.issues:
                print(f"  - {issue}")

            print("\n" + "="*70)
            print("  Next Steps")
            print("="*70)
            print("\n1. Copy .env.example to .env:")
            print("   cp .env.example .env")
            print("\n2. Add your LLM API key to .env (choose one):")
            print("   - CLAUDE_API_KEY=sk-ant-...")
            print("   - AZURE_API_KEY=...")
            print("   - GEMINI_API_KEY=...")
            print("   - LLM_ENDPOINT=http://localhost:8000 (for local vLLM)")
            print("\n3. Run health check again:")
            print("   python -m jarviscore.cli.check --validate-llm")
            print("\n4. Try the smoke test:")
            print("   python -m jarviscore.cli.smoketest")
            print()

            return False

        print("\n✓ All checks passed! Ready to use JarvisCore.\n")
        print("Next steps:")
        print("  1. Run smoke test: python -m jarviscore.cli.smoketest")
        print("  2. Try examples: python examples/calculator_agent_example.py")
        print("  3. Read guide: docs/GETTING_STARTED.md")
        print()

        return True

    def _print_status(self, label: str, status: bool, detail: str = ""):
        """Print a status line with symbol."""
        symbol = "✓" if status else ("⚠" if detail else "✗")
        label_padded = f"{label}:".ljust(30)

        if self.verbose or not status:
            print(f"{symbol} {label_padded} {detail}")
        else:
            print(f"{symbol} {label_padded} OK")

    def _mask_api_key(self, key: str) -> str:
        """Mask API key for display."""
        if not key:
            return "None"
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}...{key[-4:]}"

    async def run(self) -> bool:
        """Run all health checks."""
        self.print_header()

        # Basic checks
        print("[System Requirements]")
        python_ok = self.check_python_version()
        jarviscore_ok = self.check_jarviscore_installed()

        if not python_ok or not jarviscore_ok:
            self.print_summary()
            return False

        # Dependency checks
        deps_ok = self.check_dependencies()

        # Configuration checks
        print()
        env_exists, env_path = self.check_env_file()

        # Load .env if it exists
        if env_exists:
            from dotenv import load_dotenv
            load_dotenv(env_path)

        llm_configured = self.check_llm_config()

        # LLM connectivity test (optional)
        if self.validate_llm and any(llm_configured.values()):
            await self.validate_llm_connectivity(llm_configured)

        # Sandbox config
        self.check_sandbox_config()

        # Summary
        return self.print_summary()


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='JarvisCore Health Check - Validate your installation'
    )
    parser.add_argument(
        '--validate-llm',
        action='store_true',
        help='Test LLM API connectivity (makes actual API calls)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed information'
    )

    args = parser.parse_args()

    checker = HealthChecker(
        validate_llm=args.validate_llm,
        verbose=args.verbose
    )

    success = asyncio.run(checker.run())
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
