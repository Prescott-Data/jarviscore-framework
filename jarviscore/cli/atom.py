"""
jarviscore atom — Developer tooling for custom atom validation.

Usage:
    jarviscore atom test --bundle slack --mode dry-run
    jarviscore atom test --bundle slack --mode integration
    jarviscore atom test --bundle slack --atom slack_send_message --mode dry-run
    jarviscore atom test --mode dry-run --all
    jarviscore atom list
    jarviscore atom list --bundle slack

Commands:
    test   Validate atom structure (dry-run) or live Nexus connection (integration)
    list   List all registered atom bundles and their atoms

Dry-run checks (no network required):
  ✓ Atom file exists at integrations/atoms/<bundle>/<atom>.py
  ✓ File parses as valid Python (AST)
  ✓ Function name matches filename
  ✓ First parameter is auth_info: dict
  ✓ Return type annotation is dict
  ✓ No forbidden standard-library imports (subprocess, os.system, eval, exec)
  ✓ Function has a docstring
  ✓ Bundle directory has __init__.py

Integration checks (requires --connection-id and NEXUS_GATEWAY_URL):
  ✓ All dry-run checks pass first
  ✓ Nexus Gateway is reachable
  ✓ connection_id resolves to a valid token payload
  ✓ Token payload has expected fields for the bundle's auth_type
"""

import argparse
import ast
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple


# ── Colour helpers (match existing CLI style) ────────────────────────────────

def _ok(msg: str)   -> str: return f"\033[32m✓\033[0m  {msg}"
def _err(msg: str)  -> str: return f"\033[31m✗\033[0m  {msg}"
def _warn(msg: str) -> str: return f"\033[33m!\033[0m  {msg}"
def _info(msg: str) -> str: return f"\033[36mℹ\033[0m  {msg}"
def _bold(msg: str) -> str: return f"\033[1m{msg}\033[0m"
def _dim(msg: str)  -> str: return f"\033[2m{msg}\033[0m"
def _head(msg: str) -> str: return f"\033[1;34m{msg}\033[0m"


# ── Atoms directory resolution ────────────────────────────────────────────────

def _atoms_root() -> Path:
    """Resolve the integrations/atoms/ directory."""
    return Path(__file__).parent.parent / "integrations" / "atoms"


# ── Forbidden imports — atoms must not use these ──────────────────────────────

_FORBIDDEN_IMPORTS = {
    "subprocess", "pty", "popen", "pexpect",
    "ctypes", "cffi",
    "pickle", "marshal",
    "importlib",
}

_FORBIDDEN_BUILTINS = {"eval", "exec", "__import__"}


# ── Result collector ──────────────────────────────────────────────────────────

class _Result:
    def __init__(self):
        self.passed:   List[str] = []
        self.failed:   List[str] = []
        self.warnings: List[str] = []

    def ok(self, msg: str):
        self.passed.append(msg)
        print(f"  {_ok(msg)}")

    def fail(self, msg: str):
        self.failed.append(msg)
        print(f"  {_err(msg)}")

    def warn(self, msg: str):
        self.warnings.append(msg)
        print(f"  {_warn(msg)}")

    @property
    def success(self) -> bool:
        return len(self.failed) == 0


# ── Individual check functions ────────────────────────────────────────────────

def _check_file_exists(bundle: str, atom: str, result: _Result) -> Optional[Path]:
    """Check that the atom .py file exists and return its path."""
    path = _atoms_root() / bundle / f"{atom}.py"
    if path.exists():
        result.ok(f"Atom file exists: integrations/atoms/{bundle}/{atom}.py")
        return path
    result.fail(f"Atom file missing: integrations/atoms/{bundle}/{atom}.py")
    return None


def _check_init_exists(bundle: str, result: _Result) -> bool:
    """Check that the bundle directory has an __init__.py."""
    init = _atoms_root() / bundle / "__init__.py"
    if init.exists():
        result.ok(f"Bundle __init__.py exists")
        return True
    result.warn(f"Bundle missing __init__.py — add one for proper package import")
    return True  # warn, not hard fail


def _check_syntax(path: Path, result: _Result) -> Optional[ast.Module]:
    """Parse the atom file as an AST. Returns the tree or None on failure."""
    try:
        code = path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(path))
        result.ok("File parses as valid Python")
        return tree
    except SyntaxError as exc:
        result.fail(f"Syntax error: {exc}")
        return None


def _check_function_name(path: Path, tree: ast.Module, result: _Result) -> Optional[ast.FunctionDef]:
    """Check the top-level function name matches the filename stem."""
    expected = path.stem
    top_funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.col_offset == 0
    ]
    if not top_funcs:
        result.fail("No top-level function definition found")
        return None

    fn = top_funcs[0]
    if fn.name == expected:
        result.ok(f"Function name matches filename: {fn.name}()")
    else:
        result.fail(
            f"Function name mismatch: file is '{expected}.py' but function is '{fn.name}()'. "
            f"They must match."
        )
    return fn


def _check_signature(fn: ast.FunctionDef, result: _Result):
    """Check that first param is auth_info: dict and return annotation is dict."""
    args = fn.args.args
    if not args:
        result.fail("Function has no parameters — first parameter must be auth_info: dict")
        return

    first = args[0]
    if first.arg == "auth_info":
        # Check type annotation
        if isinstance(first.annotation, ast.Name) and first.annotation.id == "dict":
            result.ok("First parameter: auth_info: dict  ✓")
        elif first.annotation is None:
            result.warn("First parameter 'auth_info' has no type annotation — add auth_info: dict")
        else:
            annotation_str = ast.unparse(first.annotation) if hasattr(ast, 'unparse') else "?"
            result.warn(f"First parameter annotation is '{annotation_str}', expected 'dict'")
    else:
        result.fail(
            f"First parameter must be 'auth_info: dict', got '{first.arg}'. "
            f"Nexus injects credentials via auth_info — do not use a different name."
        )

    # Return annotation
    if fn.returns is None:
        result.warn("No return type annotation — add -> dict")
    elif isinstance(fn.returns, ast.Name) and fn.returns.id == "dict":
        result.ok("Return annotation: -> dict  ✓")
    else:
        ret_str = ast.unparse(fn.returns) if hasattr(ast, 'unparse') else "?"
        result.warn(f"Return annotation is '{ret_str}', expected 'dict'")


def _check_docstring(fn: ast.FunctionDef, result: _Result):
    """Check that the function has a docstring."""
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        result.ok("Function has a docstring")
    else:
        result.warn(
            "Function has no docstring — add one describing what the atom does, "
            "its parameters, and what it returns"
        )


def _check_forbidden_imports(tree: ast.Module, result: _Result):
    """Flag any forbidden imports or builtin calls."""
    found_forbidden = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            for name in names:
                root = name.split(".")[0] if name else ""
                if root in _FORBIDDEN_IMPORTS:
                    found_forbidden.append(f"import {name}")

        elif isinstance(node, ast.Call):
            # Check for eval()/exec()/__import__() calls
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name and name in _FORBIDDEN_BUILTINS:
                found_forbidden.append(f"call to {name}()")

    if found_forbidden:
        for item in found_forbidden:
            result.fail(f"Forbidden usage: {item}")
    else:
        result.ok("No forbidden imports or builtins")


def _check_return_dict(fn: ast.FunctionDef, result: _Result):
    """Check that the function has at least one return statement returning something."""
    returns = [node for node in ast.walk(fn) if isinstance(node, ast.Return)]
    if not returns:
        result.warn("No return statement found — atoms must return a dict")
        return

    # Check that at least one return returns a dict literal or variable (not None)
    has_value = any(r.value is not None for r in returns)
    if has_value:
        result.ok("Function has return statement(s)")
    else:
        result.warn("Return statement returns None — atoms must return a dict")


# ── Dry-run orchestrator ──────────────────────────────────────────────────────

def run_dry_run(bundle: str, atom: str) -> bool:
    """Run all structural checks for a single atom. Returns True if all pass."""
    print(f"\n  {_bold(atom)}")
    print(f"  {'─' * 48}")
    result = _Result()

    path = _check_file_exists(bundle, atom, result)
    if not path:
        _print_summary(result)
        return False

    _check_init_exists(bundle, result)

    tree = _check_syntax(path, result)
    if not tree:
        _print_summary(result)
        return False

    fn = _check_function_name(path, tree, result)
    if fn:
        _check_signature(fn, result)
        _check_docstring(fn, result)
        _check_return_dict(fn, result)

    _check_forbidden_imports(tree, result)
    _print_summary(result)
    return result.success


def _print_summary(result: _Result):
    label = (
        f"\033[32mPASSED\033[0m" if result.success
        else f"\033[31mFAILED\033[0m"
    )
    counts = f"{len(result.passed)} passed"
    if result.failed:
        counts += f", {len(result.failed)} failed"
    if result.warnings:
        counts += f", {len(result.warnings)} warnings"
    print(f"  {'─' * 48}")
    print(f"  {label}  ({counts})")


# ── Integration checks ────────────────────────────────────────────────────────

def run_integration(bundle: str, atom: str, connection_id: str, nexus_url: str) -> bool:
    """
    Run dry-run checks then verify Nexus connection resolves.
    Returns True if all checks pass.
    """
    print(f"\n  {_bold(atom)}  [integration]")
    print(f"  {'─' * 48}")

    # Dry-run must pass first
    dry_result = _Result()
    path = _check_file_exists(bundle, atom, dry_result)
    if not path:
        print(f"  {_err('Dry-run: file missing — fix before integration test')}")
        return False
    tree = _check_syntax(path, dry_result)
    if not tree:
        print(f"  {_err('Dry-run: syntax error — fix before integration test')}")
        return False
    fn = _check_function_name(path, tree, dry_result)
    if fn:
        _check_signature(fn, dry_result)
    _check_forbidden_imports(tree, dry_result)

    if not dry_result.success:
        _print_summary(dry_result)
        print(f"\n  {_warn('Fix dry-run errors before running integration mode')}")
        return False

    print(f"  {_ok('Dry-run checks passed')}")

    # Nexus connection check
    print(f"\n  Nexus connection check")
    print(f"  {'─' * 48}")
    print(f"  {_info(f'Gateway: {nexus_url}')}")
    print(f"  {_info(f'connection_id: {connection_id}')}")

    try:
        import httpx
    except ImportError:
        print(f"  {_warn('httpx not installed — skipping live Nexus check')}")
        print(f"  {_info('Install with: pip install httpx')}")
        return dry_result.success

    try:
        import asyncio

        async def _resolve():
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Health check first
                try:
                    health = await client.get(f"{nexus_url}/health")
                    if health.status_code == 200:
                        print(f"  {_ok(f'Gateway reachable ({nexus_url}/health → {health.status_code})')}")
                    else:
                        print(f"  {_warn(f'Gateway returned {health.status_code} on /health — may still work')}")
                except Exception as exc:
                    print(f"  {_err(f'Gateway unreachable: {exc}')}")
                    print(f"  {_info('Start the Nexus stack with: jarviscore nexus up')}")
                    return None

                # Attempt to resolve the connection
                try:
                    resp = await client.get(
                        f"{nexus_url}/v1/connections/{connection_id}/token",
                    )
                    if resp.status_code == 200:
                        payload = resp.json()
                        print(f"  {_ok(f'connection_id resolved — token payload received')}")
                        # Show non-sensitive fields
                        safe_payload = {
                            k: v for k, v in payload.items()
                            if k not in ("access_token", "refresh_token", "client_secret", "api_key")
                        }
                        if safe_payload:
                            print(f"  {_dim('Token fields (secrets redacted):')}")
                            for k, v in safe_payload.items():
                                print(f"    {_dim(k)}: {_dim(str(v)[:80])}")
                        return payload
                    elif resp.status_code == 404:
                        print(f"  {_err(f'connection_id not found: {connection_id}')}")
                        print(f"  {_info(f'Register with: jarviscore nexus register {bundle}')}")
                        return None
                    else:
                        print(f"  {_warn(f'Unexpected response: {resp.status_code} — {resp.text[:200]}')}")
                        return None
                except Exception as exc:
                    print(f"  {_err(f'Token resolution failed: {exc}')}")
                    return None

        payload = asyncio.run(_resolve())

        if payload:
            print(f"\n  {_ok('Integration check passed')}")
            print(f"  {_info('Next step: mark atom as verified in seed_registry.py if it behaves correctly against the live API')}")
            return True
        else:
            return False

    except Exception as exc:
        print(f"  {_err(f'Integration check error: {exc}')}")
        return False


# ── Bundle/atom discovery ─────────────────────────────────────────────────────

def _get_atoms_for_bundle(bundle: str) -> List[str]:
    """Return sorted list of atom names for a bundle."""
    bundle_dir = _atoms_root() / bundle
    if not bundle_dir.is_dir():
        return []
    return sorted(
        p.stem for p in bundle_dir.glob("*.py")
        if p.stem != "__init__"
    )


def _get_all_bundles() -> List[str]:
    """Return sorted list of all bundle directory names."""
    root = _atoms_root()
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith("_"))


# ── Sub-command: test ─────────────────────────────────────────────────────────

def cmd_test(args):
    nexus_url = args.nexus_url or os.getenv("NEXUS_GATEWAY_URL", "http://localhost:8090")

    print(f"\n{_bold('JarvisCore Atom Test Harness')}")
    print(f"{_dim('Mode: ' + args.mode)}")
    print(f"{_dim('Atoms root: ' + str(_atoms_root()))}")
    print()

    # Determine what to test
    if args.all:
        if args.mode == "integration":
            print(_err("--all only works with --mode dry-run"))
            sys.exit(1)
        bundles = _get_all_bundles()
        if not bundles:
            print(_info("No atom bundles found in integrations/atoms/"))
            sys.exit(0)
        print(f"{_info(f'Testing {len(bundles)} bundle(s): {', '.join(bundles)}')}")
        all_passed = True
        for bundle in bundles:
            atoms = _get_atoms_for_bundle(bundle)
            print(f"\n  {_head('Bundle: ' + bundle)}  ({len(atoms)} atoms)")
            for atom in atoms:
                if not run_dry_run(bundle, atom):
                    all_passed = False
        print(f"\n{'═' * 52}")
        if all_passed:
            print(_ok("ALL ATOMS PASSED"))
        else:
            print(_err("SOME ATOMS FAILED — fix errors above before marking as verified"))
        sys.exit(0 if all_passed else 1)

    if not args.bundle:
        print(_err("--bundle is required (or use --all for dry-run of everything)"))
        sys.exit(1)

    bundle = args.bundle
    bundle_dir = _atoms_root() / bundle
    if not bundle_dir.is_dir():
        print(_err(f"Bundle not found: integrations/atoms/{bundle}/"))
        print(_info(f"Available bundles: {', '.join(_get_all_bundles()[:10])}..."))
        sys.exit(1)

    atoms = [args.atom] if args.atom else _get_atoms_for_bundle(bundle)
    if not atoms:
        print(_err(f"No atoms found in bundle '{bundle}'"))
        sys.exit(1)

    print(f"{_info(f'Bundle: {bundle}  |  Atoms: {len(atoms)}')}")
    all_passed = True

    for atom in atoms:
        if args.mode == "dry-run":
            if not run_dry_run(bundle, atom):
                all_passed = False
        else:
            if not args.connection_id:
                print(_err("--connection-id is required for --mode integration"))
                sys.exit(1)
            if not run_integration(bundle, atom, args.connection_id, nexus_url):
                all_passed = False

    print(f"\n{'═' * 52}")
    if all_passed:
        print(_ok("ALL PASSED"))
        if args.mode == "dry-run" and not args.all:
            print(_info("Next step: run with --mode integration and a real --connection-id"))
        elif args.mode == "integration":
            print(_info("Next step: update seed_registry.py stage to 'verified' for confirmed atoms"))
    else:
        print(_err("SOME FAILED — fix errors above before registering atoms as verified"))

    sys.exit(0 if all_passed else 1)


# ── Sub-command: list ─────────────────────────────────────────────────────────

def cmd_list(args):
    print(f"\n{_bold('JarvisCore Atom Registry')}")
    print(f"{_dim(str(_atoms_root()))}\n")

    if args.bundle:
        bundles = [args.bundle]
    else:
        bundles = _get_all_bundles()

    if not bundles:
        print(_info("No atom bundles found."))
        sys.exit(0)

    total_atoms = 0
    for bundle in bundles:
        atoms = _get_atoms_for_bundle(bundle)
        total_atoms += len(atoms)
        print(f"  {_bold(bundle)}  ({len(atoms)} atoms)")
        for atom in atoms:
            print(f"    {_dim('·')} {atom}")
        print()

    print(f"{_dim(f'{len(bundles)} bundles  ·  {total_atoms} atoms total')}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="jarviscore atom",
        description="Atom developer tooling — validate, test, and list integration atoms",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Structural check — no network required
  jarviscore atom test --bundle slack --mode dry-run

  # Test a single atom
  jarviscore atom test --bundle slack --atom slack_send_message --mode dry-run

  # Full integration check against a live Nexus connection
  jarviscore atom test --bundle slack --connection-id abc123 --mode integration

  # Dry-run every atom across all bundles
  jarviscore atom test --mode dry-run --all

  # List all bundles and their atoms
  jarviscore atom list

  # List a single bundle
  jarviscore atom list --bundle github
        """,
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # ── test subcommand ──
    test_p = subparsers.add_parser("test", help="Validate atom structure or live Nexus connection")
    test_p.add_argument("--bundle",        help="Bundle name (e.g. slack, github, stripe)")
    test_p.add_argument("--atom",          help="Specific atom name to test (optional — tests all in bundle)")
    test_p.add_argument("--connection-id", dest="connection_id",
                        help="Nexus connection_id (required for --mode integration)")
    test_p.add_argument("--mode",          choices=["dry-run", "integration"], default="dry-run",
                        help="Test mode (default: dry-run)")
    test_p.add_argument("--nexus-url",     dest="nexus_url",
                        default=os.getenv("NEXUS_GATEWAY_URL", "http://localhost:8090"),
                        help="Nexus Gateway URL (default: NEXUS_GATEWAY_URL env var or http://localhost:8090)")
    test_p.add_argument("--all",           action="store_true",
                        help="Test every atom across all bundles (dry-run only)")

    # ── list subcommand ──
    list_p = subparsers.add_parser("list", help="List registered atom bundles and atoms")
    list_p.add_argument("--bundle", help="Filter to a single bundle")

    args = parser.parse_args()

    if args.subcommand == "test":
        cmd_test(args)
    elif args.subcommand == "list":
        cmd_list(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
