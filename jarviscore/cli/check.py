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
from pathlib import Path
from typing import Dict, List, Tuple
import importlib.util

LLM_TEST_TIMEOUT = 15.0


class HealthChecker:
    """Health check orchestrator for JarvisCore setup."""

    def __init__(
        self,
        validate_llm: bool = False,
        validate_typesafe: bool = False,
        verbose: bool = False,
    ):
        self.validate_llm = validate_llm
        self.validate_typesafe = validate_typesafe
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
            # `import jarviscore` is lazy; load the runtime graph and installed SDKs it used to.
            import jarviscore.core.mesh  # noqa: F401
            for sdk in ("google.genai", "openai", "anthropic"):
                try:
                    if importlib.util.find_spec(sdk) is not None:
                        importlib.import_module(sdk)
                except ImportError:
                    pass
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
            'JarvisCore Promotion': ['JARVISCORE_PROMO_TOKEN'],
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
                self.successes.append(f"{provider} configured")
                self._print_status(f"  {provider}", True, f"{key_name} is set")
            else:
                self._print_status(f"  {provider}", False, "Not configured")

        if not any(configured.values()):
            self.issues.append(
                "No LLM provider configured. AutoAgent requires at least one LLM."
            )

        return configured

    def check_typesafe_config(self) -> bool:
        """Check the optional TypeSafe decision-model configuration."""
        print("\n[Decision Model Configuration]")
        api_key = os.getenv("TYPESAFE_API_KEY")
        if not api_key:
            self._print_status("  TypeSafe Jev", False, "Not configured (optional)")
            if self.validate_typesafe:
                self.issues.append(
                    "--validate-typesafe requires TYPESAFE_API_KEY."
                )
            return False

        if importlib.util.find_spec("typesafe_sdk") is None:
            self.issues.append(
                'TYPESAFE_API_KEY is set but the optional SDK is missing. Install '
                '`jarviscore-framework[typesafe]`.'
            )
            self._print_status("  TypeSafe Jev", False, "typesafe-sdk not installed")
            return False

        self.successes.append("TypeSafe Jev configured")
        self._print_status(
            "  TypeSafe Jev",
            True,
            "TYPESAFE_API_KEY is set",
        )
        return True

    async def validate_typesafe_connectivity(self) -> None:
        """Make one typed Noul request through the public decision client."""
        print("\n[Decision Model Connectivity Test]")
        from jarviscore.execution.decisions import JevDecisionClient

        client = JevDecisionClient()
        try:
            result = await client.evaluate(
                state="JarvisCore TypeSafe connectivity check",
                questions={
                    "is_connectivity_check": {
                        "type": "noul",
                        "instructions": "Is this state a connectivity check?",
                    }
                },
            )
            probability = result.answers["is_connectivity_check"]["noul"]
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"Noul response is outside [0, 1]: {probability}")
            self.successes.append("TypeSafe Jev connectivity OK")
            self._print_status("  TypeSafe Jev API", True, result.model)
        except Exception as exc:
            error_type = type(exc).__name__
            self.issues.append(
                f"TypeSafe Jev connectivity test failed ({error_type})."
            )
            self._print_status(
                "  TypeSafe Jev API", False, f"Request failed ({error_type})"
            )
        finally:
            await client.close()

    async def validate_llm_connectivity(self, configured: Dict[str, bool]):
        """Test actual LLM connectivity."""
        print("\n[LLM Connectivity Test]")

        # Load environment
        from dotenv import load_dotenv
        load_dotenv()

        # Test configured providers concurrently; report in the fixed provider order.
        tests = {
            "JarvisCore Promotion": self._test_promo,
            "Claude": self._test_claude,
            "Azure OpenAI": self._test_azure,
            "Gemini": self._test_gemini,
            "vLLM": self._test_vllm,
        }
        selected = [p for p, is_configured in configured.items() if is_configured and p in tests]
        import asyncio

        outcomes = await asyncio.gather(
            *(tests[p]() for p in selected), return_exceptions=True
        )
        for provider, outcome in zip(selected, outcomes):
            if isinstance(outcome, BaseException):
                self.issues.append(f"{provider} test failed: {str(outcome)}")
                self._print_status(f"  {provider} API", False, str(outcome))
            elif outcome:
                self.successes.append(f"{provider} connectivity OK")
                self._print_status(f"  {provider} API", True, "Connected")
            else:
                self.issues.append(f"{provider} connection failed")
                self._print_status(f"  {provider} API", False, "Connection failed")

    async def _test_promo(self) -> bool:
        """Test promotional inference with the public client contract."""
        from jarviscore.promo import PromoLLMClient

        token = os.getenv("JARVISCORE_PROMO_TOKEN")
        if not token:
            return False
        client = PromoLLMClient(token=token, timeout=LLM_TEST_TIMEOUT)
        response = await client.generate(
            [{"role": "user", "content": "Reply with just 'OK'"}],
            temperature=0.0,
            max_tokens=10,
        )
        return response["content"].strip().upper() == "OK"

    async def _test_claude(self) -> bool:
        """Test Claude API connectivity."""
        try:
            import httpx
            from anthropic import AsyncAnthropic

            api_key = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                return False

            client = AsyncAnthropic(
                api_key=api_key,
                timeout=httpx.Timeout(LLM_TEST_TIMEOUT, connect=5),
                max_retries=0,
            )

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
            import httpx
            from openai import AsyncAzureOpenAI, BadRequestError

            client = AsyncAzureOpenAI(
                api_key=os.getenv('AZURE_API_KEY') or os.getenv('AZURE_OPENAI_KEY'),
                api_version=os.getenv('AZURE_API_VERSION', '2024-10-21'),
                azure_endpoint=os.getenv('AZURE_ENDPOINT'),
                timeout=httpx.Timeout(LLM_TEST_TIMEOUT, connect=5),
                max_retries=0,
            )

            deployment = os.getenv('AZURE_DEPLOYMENT', 'gpt-4o')
            try:
                # gpt-5.x+ models require max_completion_tokens, not max_tokens
                response = await client.chat.completions.create(
                    model=deployment,
                    messages=[{"role": "user", "content": "Reply with just 'OK'"}],
                    max_completion_tokens=10,
                )
            except BadRequestError as exc:
                if "max_completion_tokens" not in str(exc) and "max_tokens" not in str(exc):
                    raise
                # Fall back to max_tokens for older deployments (gpt-4o, gpt-4)
                response = await client.chat.completions.create(
                    model=deployment,
                    messages=[{"role": "user", "content": "Reply with just 'OK'"}],
                    max_tokens=10,
                )

            return response.choices[0].message.content.strip().upper() == 'OK'

        except Exception:
            return False

    async def _test_gemini(self) -> bool:
        """Test Gemini connectivity using the new google.genai SDK."""
        try:
            from google import genai

            client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
            model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

            import asyncio

            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents="Reply with just 'OK'"
                ),
                LLM_TEST_TIMEOUT,
            )
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
            print("\n1. Create a project (or run this inside one):")
            print("   jarviscore init my-agents && cd my-agents")
            print("\n2. Configure your environment:")
            print("   cp .env.example .env   # if .env is missing")
            print("   # Edit .env and add one of:")
            print("   #   JARVISCORE_PROMO_TOKEN=jc_trial_...")
            print("   #   CLAUDE_API_KEY=sk-ant-...")
            print("   #   AZURE_API_KEY=...")
            print("   #   GEMINI_API_KEY=...")
            print("   #   LLM_ENDPOINT=http://localhost:8000 (for local vLLM)")
            print("\n3. Run health check again:")
            print("   jarviscore check --validate-llm")
            print("\n4. Run your agents:")
            print("   jarviscore dev")
            print()

            return False

        print("\n✓ All checks passed! Ready to use JarvisCore.\n")
        print("Next steps:")
        print("  1. Run smoke test:    jarviscore smoketest")
        print("  2. New project:       jarviscore init my-agents")
        print("  3. Run it locally:    cd my-agents && jarviscore dev")
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
        typesafe_configured = self.check_typesafe_config()

        # LLM connectivity test (optional)
        if self.validate_llm and any(llm_configured.values()):
            await self.validate_llm_connectivity(llm_configured)
        if self.validate_typesafe and typesafe_configured:
            await self.validate_typesafe_connectivity()

        # Sandbox config
        self.check_sandbox_config()

        # Summary
        return self.print_summary()


def run_production_profile(destination, as_json: bool, connect: bool = True) -> int:
    """Production checklist for a jarviscore.yaml project. Exit 1 on any error."""
    import json

    from jarviscore.project import ProjectError, find_root, load_project
    from jarviscore.project.checks import ERROR, has_errors
    from jarviscore.project.checks.production import run_production_checks

    defaulted = False
    if destination is None:
        try:
            # A production checklist belongs to the prod overlay when the project has one.
            if (find_root() / "jarviscore.prod.yaml").is_file():
                destination, defaulted = "prod", True
        except ProjectError:
            pass  # load_project reports it below
    try:
        loaded = load_project(destination=destination)
    except ProjectError as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc), "results": []}, indent=2))
        else:
            print(f"✗ {exc}", file=sys.stderr)
        return 2

    results = run_production_checks(loaded, dict(os.environ), connect=connect)
    ok = not has_errors(results)
    if as_json:
        print(json.dumps({
            "ok": ok,
            "service": loaded.project.service,
            "environment": loaded.environment,
            "results": [r.as_dict() for r in results],
        }, indent=2))
        return 0 if ok else 1

    if defaulted:
        where = f"{loaded.environment}, from jarviscore.prod.yaml; pass -d <env> for another"
    elif destination is None:
        where = f"{loaded.environment}: jarviscore.yaml only; pass -d <env> to check a deployment"
    else:
        where = loaded.environment
    print(f"\nProduction checks: {loaded.project.service} ({where})\n")
    icons = {True: "✓", ERROR: "✗"}
    for r in sorted(results, key=lambda r: (r.ok, r.severity != ERROR)):
        icon = icons[True] if r.ok else icons.get(r.severity, "⚠")
        print(f"  {icon} {r.message}")
        if not r.ok and r.fix:
            print(f"      → {r.fix}")
    errors = sum(1 for r in results if not r.ok and r.severity == ERROR)
    warnings = sum(1 for r in results if not r.ok and r.severity != ERROR)
    print(f"\n{'✓ Ready' if ok else '✗ Not ready'}: {errors} error(s), {warnings} warning(s)\n")
    return 0 if ok else 1


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
        '--validate-typesafe',
        action='store_true',
        help='Test TypeSafe Jev connectivity (makes one actual API call)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed information'
    )
    parser.add_argument(
        '--profile',
        choices=['prod'],
        help='Run the production checklist against jarviscore.yaml instead of the local health check'
    )
    parser.add_argument(
        '-d', '--destination',
        help='Environment overlay for --profile prod (jarviscore.<destination>.yaml)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Machine-readable output for --profile prod'
    )
    parser.add_argument(
        '--no-connect',
        action='store_true',
        help='With --profile prod, skip checks that connect to external services'
    )

    args = parser.parse_args()

    if args.profile is None:
        profile_only = [flag for flag, used in (
            ('--json', args.json), ('-d/--destination', args.destination is not None),
            ('--no-connect', args.no_connect)) if used]
        if profile_only:
            parser.error(f"{', '.join(profile_only)} requires --profile prod")

    if args.profile == 'prod':
        sys.exit(run_production_profile(args.destination, args.json, connect=not args.no_connect))

    checker = HealthChecker(
        validate_llm=args.validate_llm,
        validate_typesafe=args.validate_typesafe,
        verbose=args.verbose
    )

    import asyncio

    success = asyncio.run(checker.run())
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
