"""
ValidationLayer — Pre-execution code quality gate.

Ported from an earlier internal agent pipeline (proprietary → OSS JarvisCore adaptation).

Three sub-validators run in sequence:
1. StaticValidator   — syntax check + result variable mandate
2. SecurityValidator — no hardcoded secrets, no eval(), no dangerous __import__
3. HTTPContractEnforcer — HTTP calls MUST have error handling (raise_for_status / status_code)

The pipeline:
    Coder generates code
        ↓
    ValidationLayer.validate_pre_execution(code)
        ↓ FAIL → return error to LLM immediately (sandbox never runs bad code)
        ↓ PASS
    SandboxExecutor.execute(code)
        ↓ FAIL → AutonomousRepair → re-validate → re-execute
        ↓ PASS
    FunctionRegistry.register_function(name, code)
"""

import ast
import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Result Types
# ─────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: Severity
    line: Optional[int] = None


@dataclass
class ValidationResult:
    is_valid: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)

    def merge(self, other: "ValidationResult") -> None:
        """Merge another result into this one (AND semantics — any failure fails all)."""
        if not other.is_valid:
            self.is_valid = False
        self.issues.extend(other.issues)

    @property
    def critical_issues(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.CRITICAL]

    @property
    def error_issues(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    def summary(self) -> str:
        if self.is_valid:
            return "✓ Validation passed"
        msgs = [f"[{i.severity.value.upper()}] {i.message}" for i in self.issues if i.severity in (Severity.CRITICAL, Severity.ERROR)]
        return "; ".join(msgs) if msgs else "Validation failed (unknown reason)"


# ─────────────────────────────────────────────────────────────────
# 1. Static Validator
# ─────────────────────────────────────────────────────────────────

class StaticValidator:
    """
    AST-based static analysis.

    Checks:
    - Valid Python syntax (ast.parse)
    - `result` variable is assigned somewhere (sandbox expects this)
    - No bare `pass` as entire function body (likely incomplete generation)
    """

    def validate(self, code: str) -> ValidationResult:
        result = ValidationResult(is_valid=True)

        # 1. Syntax check
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            result.is_valid = False
            result.issues.append(ValidationIssue(
                code="SYNTAX_ERROR",
                message=f"SyntaxError at line {e.lineno}: {e.msg}",
                severity=Severity.CRITICAL,
                line=e.lineno,
            ))
            return result  # Can't continue without valid AST

        # 2. Check result variable is assigned or returned from main()
        has_result = self._has_result_assignment(tree)
        if not has_result:
            result.issues.append(ValidationIssue(
                code="MISSING_RESULT",
                message=(
                    "No `result` variable assigned and no `main()` return detected. "
                    "The sandbox expects `result = ...` or `return result` from `main()`."
                ),
                severity=Severity.ERROR,
            ))
            result.is_valid = False

        return result

    def _has_result_assignment(self, tree: ast.Module) -> bool:
        """Check if code assigns to `result` or defines `main()` that returns a value."""
        for node in ast.walk(tree):
            # Direct assignment: result = ...
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "result":
                        return True
            # Augmented: result += ...
            if isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "result":
                    return True
            # Annotated: result: dict = ...
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "result":
                    return True
            # main() with return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "main":
                    for child in ast.walk(node):
                        if isinstance(child, ast.Return) and child.value is not None:
                            return True
        return False


# ─────────────────────────────────────────────────────────────────
# 2. Security Validator
# ─────────────────────────────────────────────────────────────────

# Patterns that indicate hardcoded credentials
_HARDCODED_SECRET_PATTERNS = [
    # API keys / tokens as string literals
    r'(?:api_key|access_token|secret|password|client_secret|private_key)\s*=\s*["\'][^"\']{8,}["\']',
    # Bearer / Basic tokens in headers
    r'"Authorization"\s*:\s*["\'](?:Bearer|Basic)\s+[A-Za-z0-9+/=]{10,}["\']',
]

# Dangerous built-in calls that should never appear in generated code
_DANGEROUS_CALLS = {"eval", "exec", "compile", "input"}

# Dangerous import patterns (os.system, subprocess.call with shell=True)
_DANGEROUS_IMPORT_ALIASES = {"__import__"}


class SecurityValidator:
    """
    Security scan for generated code.

    Rejects:
    - Hardcoded API keys / tokens as string literals
    - `eval()`, `exec()`, `compile()`, `input()`
    - `__import__` with suspicious usage
    """

    def validate(self, code: str) -> ValidationResult:
        result = ValidationResult(is_valid=True)

        # 1. Regex scan for hardcoded secrets
        for pattern in _HARDCODED_SECRET_PATTERNS:
            match = re.search(pattern, code, re.IGNORECASE)
            if match:
                result.is_valid = False
                result.issues.append(ValidationIssue(
                    code="HARDCODED_SECRET",
                    message=(
                        f"Possible hardcoded credential detected: `{match.group(0)[:80]}`. "
                        "Use environment variables or the auth context dict instead."
                    ),
                    severity=Severity.CRITICAL,
                ))

        # 2. AST scan for dangerous calls
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return result  # StaticValidator catches this

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Direct call: eval("..."), exec("...")
                if isinstance(func, ast.Name) and func.id in _DANGEROUS_CALLS:
                    result.is_valid = False
                    result.issues.append(ValidationIssue(
                        code="DANGEROUS_CALL",
                        message=f"Dangerous built-in `{func.id}()` is not allowed in generated code.",
                        severity=Severity.CRITICAL,
                        line=getattr(node, "lineno", None),
                    ))
                # __import__ usage
                if isinstance(func, ast.Name) and func.id in _DANGEROUS_IMPORT_ALIASES:
                    result.issues.append(ValidationIssue(
                        code="DANGEROUS_IMPORT",
                        message="`__import__()` detected — use standard `import` statements.",
                        severity=Severity.WARNING,
                        line=getattr(node, "lineno", None),
                    ))

        return result


# ─────────────────────────────────────────────────────────────────
# 3. HTTP Contract Enforcer
# ─────────────────────────────────────────────────────────────────

# HTTP client call patterns we detect (method attribute names)
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "request", "send"}

# Variable names that typically represent HTTP clients
_HTTP_CLIENT_NAMES = {"client", "session", "httpx", "requests", "http_client", "api_client"}


class HTTPContractEnforcer:
    """
    Enforce error handling contract on generated HTTP code.

    Rule: if the code makes HTTP calls via a recognised client
    (client.get, session.post, httpx.get, requests.get, etc.)
    it MUST have at least one of:
    - response.raise_for_status()
    - response.status_code check

    This prevents the #1 source of silent hallucinated "success" results
    in naive code generators.
    """

    def validate(self, code: str) -> Tuple[bool, List[str]]:
        """
        Returns (is_compliant, violations).

        Violations is a list of human-readable strings describing what's wrong.
        """
        violations: List[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False, ["Code has syntax errors — cannot validate HTTP contract."]

        has_http_calls = False
        has_raise_for_status = False
        has_status_check = False

        for node in ast.walk(tree):
            # Detect HTTP method calls
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                callee = node.func.value

                if attr in _HTTP_METHODS:
                    # Check if the object looks like an HTTP client
                    callee_name = None
                    if isinstance(callee, ast.Name):
                        callee_name = callee.id
                    elif isinstance(callee, ast.Attribute):
                        callee_name = callee.attr

                    if callee_name and callee_name.lower() in _HTTP_CLIENT_NAMES:
                        has_http_calls = True

                # Detect raise_for_status()
                if attr == "raise_for_status":
                    has_raise_for_status = True

            # Detect .status_code attribute access
            if isinstance(node, ast.Attribute) and node.attr == "status_code":
                has_status_check = True

        if has_http_calls and not has_raise_for_status and not has_status_check:
            violations.append(
                "HTTP calls detected but no error handling found. "
                "Add `response.raise_for_status()` after each HTTP call, "
                "or explicitly check `response.status_code`. "
                "Silent HTTP failures are a contract violation."
            )

        return len(violations) == 0, violations

    def as_validation_result(self, code: str) -> ValidationResult:
        """Wrap output in a ValidationResult for uniform interface."""
        is_compliant, violations = self.validate(code)
        result = ValidationResult(is_valid=is_compliant)
        for v in violations:
            result.issues.append(ValidationIssue(
                code="HTTP_CONTRACT_VIOLATION",
                message=v,
                severity=Severity.ERROR,
            ))
        return result


# ─────────────────────────────────────────────────────────────────
# ValidationLayer — Facade
# ─────────────────────────────────────────────────────────────────

class ValidationLayer:
    """
    Central validation facade for generated code.

    Runs all sub-validators in sequence and merges results.
    A single CRITICAL or ERROR issue marks the code as invalid.

    Usage:
        layer = ValidationLayer()
        result = layer.validate_pre_execution(code)
        if not result.is_valid:
            # Surface violations to LLM for repair
            error_msg = result.summary()
    """

    def __init__(self) -> None:
        self.static = StaticValidator()
        self.security = SecurityValidator()
        self.http_contract = HTTPContractEnforcer()

    def validate_pre_execution(
        self,
        code: str,
        skip_http_contract: bool = False,
    ) -> ValidationResult:
        """
        Run all validators on candidate code.

        Args:
            code: Python source code to validate.
            skip_http_contract: Set True for non-HTTP utility code (e.g., data processing).

        Returns:
            ValidationResult — check `.is_valid` and `.summary()`.
        """
        aggregate = ValidationResult(is_valid=True)

        # 1. Static analysis (syntax + result variable)
        static_result = self.static.validate(code)
        aggregate.merge(static_result)

        # Don't continue security/contract checks if syntax is broken
        if not static_result.is_valid:
            return aggregate

        # 2. Security scan
        security_result = self.security.validate(code)
        aggregate.merge(security_result)

        # 3. HTTP contract enforcement
        if not skip_http_contract:
            contract_result = self.http_contract.as_validation_result(code)
            aggregate.merge(contract_result)

        if aggregate.is_valid:
            logger.debug("ValidationLayer: all checks passed")
        else:
            issues = [i.message for i in aggregate.issues if i.severity in (Severity.CRITICAL, Severity.ERROR)]
            logger.warning("ValidationLayer: %d issue(s): %s", len(issues), "; ".join(issues))

        return aggregate
