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

# LLM Client
from .llm import (
    UnifiedLLMClient,
    LLMProvider,
    TOKEN_PRICING,
    create_llm_client
)

# Internet Search
from .search import (
    InternetSearch,
    create_search_client
)

# Code Generator
from .generator import (
    CodeGenerator,
    GeneratedCode,
    create_code_generator
)

# Validation Layer
from .validation import (
    ValidationLayer,
    ValidationResult,
    ValidationIssue,
    Severity,
    StaticValidator,
    SecurityValidator,
    HTTPContractEnforcer,
)

# Sandbox Executor
from .sandbox import (
    SandboxExecutor,
    ExecutionTimeout,
    create_sandbox_executor
)

# Coder Sandbox (file-capable, subprocess-aware — for Coder agent only)
from .coder_sandbox import (
    CoderSandbox,
    CoderResult,
    BashExecutor,
    GitHelper,
    BashPermissionError,
    CODER_GENERATION_SYSTEM_PROMPT,
    create_coder_sandbox,
)

# Autonomous Repair
from .repair import (
    AutonomousRepair,
    create_autonomous_repair
)

# Result Handler
from .result_handler import (
    ResultHandler,
    ResultStatus,
    ErrorCategory,
    create_result_handler
)

# Function Registry (graduated, with backward-compatible aliases)
from .code_registry import (
    FunctionRegistry,
    FunctionStatus,
    create_function_registry,
    # Backward-compatible aliases
    CodeRegistry,
    create_code_registry,
)

__all__ = [
    # LLM
    'UnifiedLLMClient',
    'LLMProvider',
    'TOKEN_PRICING',
    'create_llm_client',

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
