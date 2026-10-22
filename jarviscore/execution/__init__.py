"""
Execution Engine - Complete code generation and execution pipeline

Zero-config components:
- UnifiedLLMClient: Multi-provider LLM (vLLM, Azure, Gemini, Claude)
- InternetSearch: Web search and content extraction (SearXNG + Google Grounded)
- CodeGenerator: Natural language → Python code
- SandboxExecutor: Safe code execution with limits
- AutonomousRepair: Automatic error fixing

Everything works out of the box - just pass config dict.
"""

from importlib import import_module
from typing import TYPE_CHECKING

# Re-exports resolve on first access (PEP 562); importing one submodule no
# longer loads every LLM SDK and HTTP client in the package.
_LAZY = {
    **dict.fromkeys(["UnifiedLLMClient", "LLMProvider", "TOKEN_PRICING", "create_llm_client"], "llm"),
    **dict.fromkeys(
        ["DecisionClientError", "DecisionResult", "JevDecisionClient", "create_decision_client"],
        "decisions"),
    **dict.fromkeys(["InternetSearch", "create_search_client"], "search"),
    **dict.fromkeys(["CodeGenerator", "GeneratedCode", "create_code_generator"], "generator"),
    **dict.fromkeys([
        "ValidationLayer", "ValidationResult", "ValidationIssue", "Severity",
        "StaticValidator", "SecurityValidator", "HTTPContractEnforcer",
    ], "validation"),
    **dict.fromkeys(["SandboxExecutor", "ExecutionTimeout", "create_sandbox_executor"], "sandbox"),
    **dict.fromkeys([
        "CoderSandbox", "CoderResult", "BashExecutor", "GitHelper", "BashPermissionError",
        "CODER_GENERATION_SYSTEM_PROMPT", "create_coder_sandbox",
    ], "coder_sandbox"),
    **dict.fromkeys([
        "BlobSnapshotStore", "SandboxBinding", "SnapshotEntry", "SourceRef", "SourceSnapshot",
        "WorkspaceDelta", "WorkspaceDeltaConflict", "cleanup_stale_bindings",
    ], "workspace"),
    **dict.fromkeys([
        "GitHubRepositorySource", "GitHubSourceRequestError", "SnapshotLimitExceeded",
        "SnapshotLimits", "SourceAdapter", "SourceAdapterError", "SourceContractError",
        "SourceIntegrityError", "capture_source",
    ], "sources"),
    **dict.fromkeys(["AutonomousRepair", "create_autonomous_repair"], "repair"),
    **dict.fromkeys(
        ["ResultHandler", "ResultStatus", "ErrorCategory", "create_result_handler"], "result_handler"),
    **dict.fromkeys([
        "FunctionRegistry", "FunctionStatus", "create_function_registry",
        "CodeRegistry", "create_code_registry",
    ], "code_registry"),
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{_LAZY[name]}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))


if TYPE_CHECKING:
    from .llm import UnifiedLLMClient, LLMProvider, TOKEN_PRICING, create_llm_client
    from .decisions import (
        DecisionClientError, DecisionResult, JevDecisionClient, create_decision_client,
    )
    from .search import InternetSearch, create_search_client
    from .generator import CodeGenerator, GeneratedCode, create_code_generator
    from .validation import (
        ValidationLayer, ValidationResult, ValidationIssue, Severity,
        StaticValidator, SecurityValidator, HTTPContractEnforcer,
    )
    from .sandbox import SandboxExecutor, ExecutionTimeout, create_sandbox_executor
    from .coder_sandbox import (
        CoderSandbox, CoderResult, BashExecutor, GitHelper, BashPermissionError,
        CODER_GENERATION_SYSTEM_PROMPT, create_coder_sandbox,
    )
    from .workspace import (
        BlobSnapshotStore, SandboxBinding, SnapshotEntry, SourceRef, SourceSnapshot,
        WorkspaceDelta, WorkspaceDeltaConflict, cleanup_stale_bindings,
    )
    from .sources import (
        GitHubRepositorySource, GitHubSourceRequestError, SnapshotLimitExceeded, SnapshotLimits,
        SourceAdapter, SourceAdapterError, SourceContractError, SourceIntegrityError,
        capture_source,
    )
    from .repair import AutonomousRepair, create_autonomous_repair
    from .result_handler import ResultHandler, ResultStatus, ErrorCategory, create_result_handler
    from .code_registry import (
        FunctionRegistry, FunctionStatus, create_function_registry,
        CodeRegistry, create_code_registry,
    )

__all__ = [
    # LLM
    'UnifiedLLMClient',
    'LLMProvider',
    'TOKEN_PRICING',
    'create_llm_client',

    # Decision models
    'DecisionClientError',
    'DecisionResult',
    'JevDecisionClient',
    'create_decision_client',

    # Search
    'InternetSearch',
    'create_search_client',

    # Generator
    'CodeGenerator',
    'GeneratedCode',
    'create_code_generator',

    # Validation
    'ValidationLayer',
    'ValidationResult',
    'ValidationIssue',
    'Severity',
    'StaticValidator',
    'SecurityValidator',
    'HTTPContractEnforcer',

    # Sandbox (API-safe, no file access)
    'SandboxExecutor',
    'ExecutionTimeout',
    'create_sandbox_executor',

    # Coder Sandbox (file + subprocess access, Coder agent only)
    'CoderSandbox',
    'CoderResult',
    'BashExecutor',
    'GitHelper',
    'BashPermissionError',
    'CODER_GENERATION_SYSTEM_PROMPT',
    'create_coder_sandbox',

    # Blob-backed ephemeral workspaces
    'SourceRef',
    'SnapshotEntry',
    'SourceSnapshot',
    'WorkspaceDelta',
    'WorkspaceDeltaConflict',
    'cleanup_stale_bindings',
    'BlobSnapshotStore',
    'SandboxBinding',
    'SnapshotLimits',
    'SnapshotLimitExceeded',
    'GitHubRepositorySource',
    'GitHubSourceRequestError',
    'SourceAdapter',
    'SourceAdapterError',
    'SourceContractError',
    'SourceIntegrityError',
    'capture_source',

    # Repair
    'AutonomousRepair',
    'create_autonomous_repair',

    # Result Handler
    'ResultHandler',
    'ResultStatus',
    'ErrorCategory',
    'create_result_handler',

    # Function Registry
    'FunctionRegistry',
    'FunctionStatus',
    'create_function_registry',
    # Backward-compatible aliases
    'CodeRegistry',
    'create_code_registry',
]
