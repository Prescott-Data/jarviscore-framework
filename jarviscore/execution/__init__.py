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

import importlib as _importlib
from typing import TYPE_CHECKING as _TYPE_CHECKING

# Names load on first use (PEP 562), so importing one part of the execution
# package (the sandbox worker, say) does not import every LLM SDK.
_EXPORTS = {
    "llm": ("UnifiedLLMClient", "LLMProvider", "TOKEN_PRICING", "create_llm_client"),
    "decisions": ("DecisionClientError", "DecisionClient", "DecisionResult", "JevDecisionClient", "create_decision_client"),
    "search": ("InternetSearch", "create_search_client"),
    "generator": ("CodeGenerator", "GeneratedCode", "create_code_generator"),
    "validation": ("ValidationLayer", "ValidationResult", "ValidationIssue", "Severity", "StaticValidator", "SecurityValidator", "HTTPContractEnforcer"),
    "sandbox": ("SandboxExecutor", "ExecutionTimeout", "create_sandbox_executor"),
    "coder_sandbox": ("CoderSandbox", "CoderResult", "BashExecutor", "GitHelper", "BashPermissionError", "CODER_GENERATION_SYSTEM_PROMPT", "create_coder_sandbox"),
    "workspace": ("BlobSnapshotStore", "SandboxBinding", "SnapshotEntry", "SourceRef", "SourceSnapshot", "WorkspaceDelta", "WorkspaceDeltaConflict", "cleanup_stale_bindings"),
    "sources": ("GitHubRepositorySource", "GitHubSourceRequestError", "SnapshotLimitExceeded", "SnapshotLimits", "SourceAdapter", "SourceAdapterError", "SourceContractError", "SourceIntegrityError", "capture_source"),
    "repair": ("AutonomousRepair", "create_autonomous_repair"),
    "result_handler": ("ResultHandler", "ResultStatus", "ErrorCategory", "create_result_handler"),
    "code_registry": ("FunctionRegistry", "FunctionStatus", "create_function_registry", "shared_function_registry", "CodeRegistry", "create_code_registry"),
}
_SOURCE = {name: module for module, names in _EXPORTS.items() for name in names}


def __getattr__(name):
    module = _SOURCE.get(name)
    if module is None:
        try:
            value = _importlib.import_module(f".{name}", __name__)
        except ModuleNotFoundError as exc:
            if exc.name != f"{__name__}.{name}":
                raise
            raise AttributeError(f"module 'jarviscore.execution' has no attribute {name!r}") from None
        globals()[name] = value
        return value
    value = getattr(_importlib.import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


if _TYPE_CHECKING:  # pragma: no cover - for type checkers and IDEs
    from .llm import (UnifiedLLMClient, LLMProvider, TOKEN_PRICING, create_llm_client)
    from .decisions import (DecisionClientError, DecisionClient, DecisionResult, JevDecisionClient, create_decision_client)
    from .search import (InternetSearch, create_search_client)
    from .generator import (CodeGenerator, GeneratedCode, create_code_generator)
    from .validation import (ValidationLayer, ValidationResult, ValidationIssue, Severity, StaticValidator, SecurityValidator, HTTPContractEnforcer)
    from .sandbox import (SandboxExecutor, ExecutionTimeout, create_sandbox_executor)
    from .coder_sandbox import (CoderSandbox, CoderResult, BashExecutor, GitHelper, BashPermissionError, CODER_GENERATION_SYSTEM_PROMPT, create_coder_sandbox)
    from .workspace import (BlobSnapshotStore, SandboxBinding, SnapshotEntry, SourceRef, SourceSnapshot, WorkspaceDelta, WorkspaceDeltaConflict, cleanup_stale_bindings)
    from .sources import (GitHubRepositorySource, GitHubSourceRequestError, SnapshotLimitExceeded, SnapshotLimits, SourceAdapter, SourceAdapterError, SourceContractError, SourceIntegrityError, capture_source)
    from .repair import (AutonomousRepair, create_autonomous_repair)
    from .result_handler import (ResultHandler, ResultStatus, ErrorCategory, create_result_handler)
    from .code_registry import (FunctionRegistry, FunctionStatus, create_function_registry, shared_function_registry, CodeRegistry, create_code_registry)

__all__ = [
    # LLM
    'UnifiedLLMClient',
    'LLMProvider',
    'TOKEN_PRICING',
    'create_llm_client',

    # Decision models
    'DecisionClientError',
    'DecisionClient',
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
    'shared_function_registry',
    # Backward-compatible aliases
    'CodeRegistry',
    'create_code_registry',
]
